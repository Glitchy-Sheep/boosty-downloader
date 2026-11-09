"""Canonical saves remain durable when optional index updates cannot complete."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library import (
    _index_observations,
)
from boosty_downloader.infrastructure.library import (
    index as index_module,
)
from boosty_downloader.infrastructure.library import (
    index_writer as writer_module,
)
from boosty_downloader.infrastructure.library._index_models import (
    IndexAuthor,
    IndexPost,
)
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.index_sources import (
    read_author_source,
    read_locked_fingerprint,
    read_post_source,
)
from boosty_downloader.infrastructure.library.indexed_post_store import (
    IndexedJsonPostStore,
)
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy import RowMapping

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
POST_ID = 'abcdefgh-first'
AUDIO_ID = 'audio:lesson'


@dataclass(frozen=True)
class LibraryFixture:
    root: Path
    raw: JsonPostStore
    store: IndexedJsonPostStore
    index: LibraryIndex
    folder: str
    record: StoredPost
    warnings: list[str]


@pytest.fixture
def library(tmp_path: Path) -> LibraryFixture:
    root = tmp_path / 'library'
    initialize_library(root)
    raw = JsonPostStore(root)
    record = StoredPost(
        post=PostMetadata(
            POST_ID,
            'writer',
            f'https://boosty.to/writer/posts/{POST_ID}',
            'Original post',
            NOW,
            NOW,
        ),
        sync=PostSync(NOW, NOW),
        blocks=[MediaBlock(AUDIO_ID)],
        media={AUDIO_ID: MediaEntry(MediaKind.audio, MediaStatus.pending, NOW, 0)},
    )
    folder = raw.choose_post_folder(record.post)
    raw.save_post(folder, record)
    raw.save_author(AuthorInfo('writer', NOW, title='Original blog'))
    JsonPostMarks(root).save_marks(
        'writer',
        POST_ID,
        PostMarks(favorite=True, positions={AUDIO_ID: PlaybackPosition(12.5)}),
    )
    warnings: list[str] = []
    index = LibraryIndex(root)
    store = IndexedJsonPostStore(root, index=index, warn=warnings.append)
    store.prepare()
    return LibraryFixture(root, raw, store, index, folder, record, warnings)


def _rows(index: LibraryIndex) -> list[RowMapping]:
    with index.connect() as connection:
        return list(
            connection.execute(select(IndexPost).order_by(IndexPost.post_id)).mappings()
        )


def _author(index: LibraryIndex) -> RowMapping:
    with index.connect() as connection:
        return (
            connection.execute(
                select(IndexAuthor).where(IndexAuthor.author == 'writer')
            )
            .mappings()
            .one()
        )


def _saved_record(library: LibraryFixture) -> StoredPost:
    located = library.raw.find_post('writer', POST_ID)
    assert located is not None
    assert located.record is not None
    return located.record


def _saved_author(library: LibraryFixture) -> AuthorInfo:
    author = library.raw.load_author('writer')
    assert author is not None
    return author


def _locked(
    record: StoredPost, *, post_id: str = POST_ID, title: str = 'Locked'
) -> LockedPost:
    return LockedPost(replace(record.post, id=post_id, title=title), NOW)


def test_constructor_and_lookup_do_not_create_index(tmp_path: Path):
    root = tmp_path / 'absent'
    index = LibraryIndex(root)
    store = IndexedJsonPostStore(root, index=index, warn=Mock())
    assert store.find_post('writer', POST_ID) is None
    assert store.load_author('writer') is None
    assert store.load_locked_post('writer', POST_ID) is None
    assert not root.exists()


def test_prepare_and_post_saves_do_not_repeat_full_preparation(
    library: LibraryFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    ensure = Mock(wraps=library.index.ensure)
    monkeypatch.setattr(library.index, 'ensure', ensure)
    scan = Mock(side_effect=AssertionError('Unexpected whole-library scan'))
    monkeypatch.setattr(index_module, 'scan_authors', scan)
    library.store.prepare()
    library.store.save_post(library.folder, library.record)
    library.store.save_post(library.folder, library.record)
    ensure.assert_not_called()
    scan.assert_not_called()
    assert not library.warnings


def test_post_save_refreshes_complete_projection_and_preserves_marks(
    library: LibraryFixture,
):
    marks_file = library.root / library.folder / 'viewer.json'
    before = marks_file.read_bytes()
    library.record.media[AUDIO_ID].status = MediaStatus.downloaded
    library.record.media[AUDIO_ID].path = 'lesson.mp3'
    library.record.media[AUDIO_ID].size = 123
    library.record.post.title = 'Updated title'
    library.store.save_post(library.folder, library.record)
    row = _rows(library.index)[0]
    assert row['title'] == 'Updated title'
    assert row['downloaded_counts']['audio'] == 1
    assert sum(row['downloaded_counts'].values()) == 1
    assert row['favorite'] is True
    with library.index.connect() as connection:
        assert connection.scalar(text('SELECT playback_position FROM media')) == 12.5
        assert (
            connection.scalar(text('SELECT original_title FROM posts_fts'))
            == 'Updated title'
        )
    assert marks_file.read_bytes() == before
    assert not library.warnings


def test_canonical_save_failure_is_not_an_index_warning(library: LibraryFixture):
    before = _rows(library.index)
    with pytest.raises(ValueError, match='Invalid folder'):
        library.store.save_post('elsewhere', library.record)
    assert _rows(library.index) == before
    assert not library.warnings


def test_failed_index_update_warns_once_and_stops_later_attempts(
    library: LibraryFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    update = Mock(side_effect=OperationalError('unused', {}, RuntimeError('locked')))
    monkeypatch.setattr(library.index, 'upsert_post', update)
    library.store.save_post(library.folder, library.record)
    library.record.post.title = 'Second successful canonical save'
    library.store.save_post(library.folder, library.record)
    library.store.save_author(AuthorInfo('writer', NOW, title='Later author'))
    library.store.save_locked_post(_locked(library.record))
    library.store.prepare()
    update.assert_called_once()
    assert _saved_record(library).post.title == library.record.post.title
    assert _saved_author(library).title == 'Later author'
    assert library.raw.load_locked_post('writer', POST_ID) is not None
    assert len(library.warnings) == 1
    assert library.warnings[0].startswith('Library index update failed')
    assert str(library.index.path) in library.warnings[0]
    assert '--cache-dir' in library.warnings[0]
    assert 'reindex' in library.warnings[0]
    assert 'unused' not in library.warnings[0]


def test_failed_preparation_does_not_block_canonical_saves(
    library: LibraryFixture, tmp_path: Path
):
    path = tmp_path / 'unusable' / 'index.db'
    path.mkdir(parents=True)
    warnings: list[str] = []
    store = IndexedJsonPostStore(
        library.root,
        index=LibraryIndex(library.root, index_path=path),
        warn=warnings.append,
    )
    store.prepare()
    library.record.post.title = 'Saved without cache'
    store.save_post(library.folder, library.record)
    store.save_author(AuthorInfo('writer', NOW, title='Saved author'))
    assert _saved_record(library).post.title == 'Saved without cache'
    assert len(warnings) == 1
    assert path.is_dir()


def test_cancellation_propagates_after_the_canonical_save(
    library: LibraryFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        library.index, 'upsert_post', Mock(side_effect=asyncio.CancelledError)
    )
    library.record.post.title = 'Durable before cancellation'
    with pytest.raises(asyncio.CancelledError):
        library.store.save_post(library.folder, library.record)
    assert _saved_record(library).post.title == library.record.post.title
    assert not library.warnings


def test_corrupt_marks_disable_only_indexing(library: LibraryFixture):
    marks_file = library.root / library.folder / 'viewer.json'
    marks_file.write_bytes(b'broken viewing marks')
    library.record.post.title = 'Saved despite unreadable marks'
    library.store.save_post(library.folder, library.record)
    assert _saved_record(library).post.title == library.record.post.title
    assert marks_file.read_bytes() == b'broken viewing marks'
    assert len(library.warnings) == 1
    assert 'InvalidViewerRecordError' in library.warnings[0]


def test_access_changes_keep_saved_body_and_marks(library: LibraryFixture):
    marks_file = library.root / library.folder / 'viewer.json'
    before = marks_file.read_bytes()
    library.store.save_locked_post(_locked(library.record))
    row = _rows(library.index)[0]
    assert row['access'] == 'locked'
    assert row['title'] == 'Locked'
    assert row['folder'] == library.folder
    assert row['favorite'] is True
    assert row['current_counts']['audio'] == 1
    assert sum(row['current_counts'].values()) == 1
    assert _author(library.index)['locked_post_count'] == 1
    assert _author(library.index)['locked_json_synced'] is True
    library.store.clear_locked_post('writer', POST_ID)
    row = _rows(library.index)[0]
    assert row['access'] == 'open'
    assert row['title'] == library.record.post.title
    assert row['favorite'] is True
    assert _author(library.index)['locked_post_count'] == 0
    assert marks_file.read_bytes() == before
    assert not library.warnings


def test_locked_only_post_gets_a_row_and_clearing_removes_it(library: LibraryFixture):
    post_id = 'ijklmnop-locked-only'
    before = set((library.root / 'writer').iterdir())
    library.store.save_locked_post(_locked(library.record, post_id=post_id))
    locked = next(row for row in _rows(library.index) if row['post_id'] == post_id)
    assert locked['folder'] is None
    assert locked['access'] == 'locked'
    assert set((library.root / 'writer').iterdir()) == before
    library.store.clear_locked_post('writer', post_id)
    assert [row['post_id'] for row in _rows(library.index)] == [POST_ID]
    assert _author(library.index)['post_count'] == 1


def test_recordless_folder_does_not_keep_cleared_locked_row(library: LibraryFixture):
    library.store.save_locked_post(_locked(library.record))
    (library.root / library.folder / 'post.json').unlink()
    marks_file = library.root / library.folder / 'viewer.json'
    before = marks_file.read_bytes()
    library.store.clear_locked_post('writer', POST_ID)
    assert _rows(library.index) == []
    assert marks_file.read_bytes() == before


def test_author_save_does_not_claim_unindexed_access_observations(
    library: LibraryFixture,
):
    before = _author(library.index)
    library.raw.save_locked_post(_locked(library.record))
    library.store.save_author(AuthorInfo('writer', NOW, title='New blog title'))
    after = _author(library.index)
    assert after['title'] == 'New blog title'
    assert after['locked_json_mtime_ns'] == before['locked_json_mtime_ns']
    assert after['locked_json_size'] == before['locked_json_size']
    assert _rows(library.index)[0]['access'] == 'open'
    assert read_locked_fingerprint(library.root, 'writer') is not None


def test_stale_access_snapshot_stays_dirty_across_later_updates(
    library: LibraryFixture,
):
    library.store.save_locked_post(_locked(library.record))
    library.raw.save_locked_post(
        _locked(library.record, title='Unindexed external change')
    )
    other = _locked(library.record, post_id='ijklmnop-other')
    library.store.save_locked_post(other)
    assert _author(library.index)['locked_json_synced'] is False
    first = next(row for row in _rows(library.index) if row['post_id'] == POST_ID)
    assert first['title'] == 'Locked'
    library.store.save_locked_post(
        replace(other, teaser_path='.boosty-downloader/teasers/new.jpg')
    )
    library.store.save_author(AuthorInfo('writer', NOW, title='Still dirty'))
    assert _author(library.index)['locked_json_synced'] is False


def test_dirty_access_state_is_not_confused_with_missing_file(library: LibraryFixture):
    library.store.save_locked_post(_locked(library.record))
    library.raw.save_locked_post(_locked(library.record, title='Unindexed change'))
    library.store.save_locked_post(_locked(library.record, post_id='ijklmnop-other'))
    assert _author(library.index)['locked_json_synced'] is False
    (library.root / 'writer' / '.boosty-downloader' / 'locked.json').unlink()
    library.store.clear_locked_post('writer', 'ijklmnop-other')
    author = _author(library.index)
    assert author['locked_json_mtime_ns'] is None
    assert author['locked_json_size'] is None
    assert author['locked_json_synced'] is False
    assert _rows(library.index)[0]['access'] == 'locked'
    library.index.rebuild()
    assert _author(library.index)['locked_json_synced'] is True
    assert _rows(library.index)[0]['access'] == 'open'


def test_access_transaction_rolls_back_metadata_and_post_on_failure(
    library: LibraryFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    before = _author(library.index)
    posts = _rows(library.index)
    monkeypatch.setattr(
        _index_observations,
        'write_posts',
        Mock(side_effect=OperationalError('statement', {}, RuntimeError('locked'))),
    )
    library.store.save_locked_post(_locked(library.record))
    assert _author(library.index) == before
    assert _rows(library.index) == posts
    assert library.raw.load_locked_post('writer', POST_ID) is not None
    assert len(library.warnings) == 1


def test_missing_index_rebuild_during_access_update_marks_complete(
    library: LibraryFixture,
):
    library.index.path.unlink()
    library.store.save_locked_post(_locked(library.record))
    assert _rows(library.index)[0]['access'] == 'locked'
    assert _author(library.index)['locked_json_synced'] is True
    assert not library.warnings


def test_direct_readers_return_known_sources_without_scans(library: LibraryFixture):
    author = read_author_source(library.root, 'writer')
    post = read_post_source(library.root, library.folder)
    assert author.info is not None
    assert author.info.title == 'Original blog'
    assert author.author_fingerprint is not None
    assert post is not None
    assert post.post.record == library.record
    assert post.marks.favorite is True
    assert read_author_source(library.root, 'unknown').info is None


@pytest.mark.parametrize(
    'folder',
    [
        '../elsewhere',
        '/absolute',
        'writer/post/extra',
        'writer//post',
        'writer/../post',
    ],
)
def test_direct_post_reader_rejects_invalid_relative_paths(
    library: LibraryFixture, folder: str
):
    with pytest.raises(
        ValueError, match=r'Invalid relative post folder|single portable directory'
    ):
        read_post_source(library.root, folder)


def test_direct_post_reader_rejects_another_posts_access(library: LibraryFixture):
    locked = _locked(library.record, post_id='ijklmnop-other')
    with pytest.raises(ValueError, match='another post'):
        read_post_source(library.root, library.folder, locked_post=locked)


def test_access_snapshot_failure_does_not_block_the_canonical_write(
    library: LibraryFixture,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        writer_module,
        'read_locked_fingerprint',
        Mock(side_effect=OSError('unreadable snapshot')),
    )
    library.store.save_locked_post(_locked(library.record))
    assert library.raw.load_locked_post('writer', POST_ID) is not None
    assert len(library.warnings) == 1
    assert _rows(library.index)[0]['access'] == 'open'


def test_first_save_can_prepare_a_missing_index(
    library: LibraryFixture, tmp_path: Path
):
    root = tmp_path / 'new-library'
    initialize_library(root)
    index = LibraryIndex(root)
    warnings: list[str] = []
    store = IndexedJsonPostStore(root, index=index, warn=warnings.append)
    store.save_author(AuthorInfo('writer', NOW))
    store.save_locked_post(_locked(library.record))
    assert _author(index)['locked_json_synced'] is True
    assert _rows(index)[0]['access'] == 'locked'
    assert not warnings


def test_direct_post_reader_rejects_another_authors_access(library: LibraryFixture):
    locked = LockedPost(replace(library.record.post, author='other'), NOW)
    with pytest.raises(ValueError, match='another post'):
        read_post_source(library.root, library.folder, locked_post=locked)
