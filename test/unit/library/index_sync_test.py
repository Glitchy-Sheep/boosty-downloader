"""Incremental preparation follows canonical changes and preserves source ownership."""

from __future__ import annotations

import errno
import shutil
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from sqlalchemy import Engine, event, select, text
from unit.library import index_test
from unit.library.index_test import (
    AUDIO_ID,
    NOW,
    POST_ID,
    FileSnapshot,
    LibraryFixture,
)

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import AuthorInfo, LockedPost, TextBlock
from boosty_downloader.infrastructure.library import _index_sync, index_sources
from boosty_downloader.infrastructure.library._index_models import (
    IndexAuthor,
    IndexMedia,
    IndexPost,
    IndexPostTag,
)
from boosty_downloader.infrastructure.library._index_sync import inventory_sources
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_RECORD_FILENAME,
    AUTHOR_SERVICE_FOLDER,
    LOCKED_RECORD_FILENAME,
)
from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidPostRecordError,
    InvalidViewerRecordError,
)
from boosty_downloader.infrastructure.library.index import IndexSyncCounts, LibraryIndex
from boosty_downloader.infrastructure.library.json_store import (
    POST_RECORD_FILENAME,
    write_post_record,
)
from boosty_downloader.infrastructure.library.post_marks import (
    VIEWER_RECORD_FILENAME,
    JsonPostMarks,
)

if TYPE_CHECKING:
    from sqlalchemy import RowMapping


library = index_test.library


@pytest.fixture
def index(library: LibraryFixture) -> LibraryIndex:
    result = LibraryIndex(library.root)
    result.ensure()
    return result


def _post_rows(index: LibraryIndex) -> list[RowMapping]:
    with index.connect() as connection:
        return list(
            connection.execute(
                select(IndexPost).order_by(IndexPost.author, IndexPost.post_id)
            ).mappings()
        )


def _canonical_snapshot(root: Path) -> dict[Path, FileSnapshot]:
    return {
        path: FileSnapshot(path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob('*')
        if path.is_file() and not path.name.startswith('index.db')
    }


def _author_file(library: LibraryFixture, name: str) -> Path:
    return library.root / 'writer' / AUTHOR_SERVICE_FOLDER / name


def _post_file(library: LibraryFixture, name: str) -> Path:
    return library.root / library.folder / name


def _indexed(index: LibraryIndex, post_id: str = POST_ID) -> RowMapping:
    return next(row for row in _post_rows(index) if row['post_id'] == post_id)


def _locked(library: LibraryFixture, post_id: str = POST_ID) -> LockedPost:
    return LockedPost(replace(library.record.post, id=post_id), NOW)


def _symlink(target: Path, link: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except NotImplementedError:
        pytest.skip('Symbolic links are unavailable')
    except OSError as error:
        if error.errno in {errno.EPERM, errno.EACCES, errno.ENOTSUP}:
            pytest.skip('Symbolic links are unavailable')
        raise


def test_missing_index_rebuilds_without_second_source_scan(
    library: LibraryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    incremental = Mock(side_effect=AssertionError('Redundant incremental scan'))
    monkeypatch.setattr(_index_sync, 'inventory_sources', incremental)
    index = LibraryIndex(library.root)
    assert index.synchronize() == IndexSyncCounts(rebuilt=True)
    assert _indexed(index)['title'] == library.record.post.title
    incremental.assert_not_called()


def test_unchanged_index_reads_no_canonical_json_or_media(
    library: LibraryFixture, index: LibraryIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _canonical_snapshot(library.root)
    unreadable = Mock(side_effect=AssertionError('Unchanged source was read'))
    monkeypatch.setattr(index_sources, '_read_source', unreadable)
    monkeypatch.setattr(index_sources, 'find_cover_path', unreadable)
    monkeypatch.setattr(Path, 'rglob', unreadable)
    assert index.synchronize() == IndexSyncCounts()
    unreadable.assert_not_called()
    monkeypatch.undo()
    assert _canonical_snapshot(library.root) == before


def test_changed_post_updates_search_tags_and_fingerprints(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    library.record.post.title = 'Revised lesson'
    library.record.post.tags = ['new', 'new', 'other']
    library.record.blocks = [
        TextBlock([PostDataChunkText.TextFragment('A revised body')])
    ]
    library.store.save_post(library.folder, library.record)
    before = _canonical_snapshot(library.root)
    assert index.synchronize() == IndexSyncCounts(posts_updated=1)
    row = _indexed(index)
    assert row['title'] == 'Revised lesson'
    assert row['tags'] == ['new', 'new', 'other']
    assert (
        row['post_json_size']
        == _post_file(library, POST_RECORD_FILENAME).stat().st_size
    )
    with index.connect() as connection:
        assert set(connection.scalars(select(IndexPostTag.tag))) == {'new', 'other'}
        assert (
            connection.scalar(
                text("SELECT count(*) FROM posts_fts WHERE posts_fts MATCH 'original'")
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM posts_fts WHERE posts_fts MATCH 'revised'")
            )
            == 1
        )
    assert _canonical_snapshot(library.root) == before
    assert index.synchronize() == IndexSyncCounts()


def test_changed_and_removed_viewer_record_reset_marks_and_playback(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    JsonPostMarks(library.root).save_marks(
        'writer', POST_ID, PostMarks(positions={AUDIO_ID: PlaybackPosition(40)})
    )
    assert index.synchronize() == IndexSyncCounts(posts_updated=1)
    assert _indexed(index)['favorite'] is False
    assert _indexed(index)['seen_at'] is None
    with index.connect() as connection:
        assert (
            connection.scalar(
                select(IndexMedia.playback_position).where(
                    IndexMedia.media_id == AUDIO_ID
                )
            )
            == 40
        )
    _post_file(library, VIEWER_RECORD_FILENAME).unlink()
    assert index.synchronize() == IndexSyncCounts(posts_updated=1)
    row = _indexed(index)
    assert row['viewer_json_mtime_ns'] is None
    with index.connect() as connection:
        assert (
            connection.scalar(
                select(IndexMedia.playback_position).where(
                    IndexMedia.media_id == AUDIO_ID
                )
            )
            is None
        )


def test_author_metadata_changes_do_not_read_unchanged_post(
    library: LibraryFixture, index: LibraryIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    library.store.save_author(AuthorInfo('writer', NOW, title='Renamed'))
    read_post = Mock(side_effect=AssertionError('Unchanged post was read'))
    monkeypatch.setattr(_index_sync, 'read_post_source_with_observations', read_post)
    assert index.synchronize() == IndexSyncCounts(authors_updated=1)
    with index.connect() as connection:
        assert connection.scalar(select(IndexAuthor.title)) == 'Renamed'
        assert connection.scalar(select(IndexAuthor.post_count)) == 1
    _author_file(library, AUTHOR_RECORD_FILENAME).unlink()
    assert index.synchronize() == IndexSyncCounts(authors_updated=1)
    with index.connect() as connection:
        assert connection.scalar(select(IndexAuthor.title)) is None
    read_post.assert_not_called()


def test_access_observation_addition_update_and_removal(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    locked = _locked(library)
    locked.post.title = 'Current locked title'
    library.store.save_locked_post(locked)
    assert index.synchronize() == IndexSyncCounts(authors_updated=1, posts_updated=1)
    row = _indexed(index)
    assert row['access'] == PostAccess.locked.value
    assert row['title'] == 'Current locked title'
    assert row['folder'] == library.folder
    locked.post.title = 'Changed locked title'
    library.store.save_locked_post(locked)
    assert index.synchronize().posts_updated == 1
    assert _indexed(index)['title'] == 'Changed locked title'
    _author_file(library, LOCKED_RECORD_FILENAME).unlink()
    assert index.synchronize() == IndexSyncCounts(authors_updated=1, posts_updated=1)
    assert _indexed(index)['access'] == PostAccess.open.value
    assert _indexed(index)['title'] == library.record.post.title


def test_dirty_missing_locked_source_reconciles_cached_overlay(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    library.store.save_locked_post(_locked(library))
    index.synchronize()
    _author_file(library, LOCKED_RECORD_FILENAME).unlink()
    with closing(sqlite3.connect(index.path)) as connection:
        connection.execute(
            'UPDATE authors SET locked_json_synced=0, locked_json_mtime_ns=NULL, locked_json_size=NULL'
        )
        connection.commit()
    assert index.synchronize() == IndexSyncCounts(authors_updated=1, posts_updated=1)
    assert _indexed(index)['access'] == PostAccess.open.value
    assert index.synchronize() == IndexSyncCounts()


def test_locked_only_addition_and_removal_clear_fts(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    locked_id = 'lockedid-other'
    library.store.save_locked_post(_locked(library, locked_id))
    assert index.synchronize() == IndexSyncCounts(authors_updated=1, posts_updated=1)
    assert _indexed(index, locked_id)['folder'] is None
    library.store.clear_locked_post('writer', locked_id)
    assert index.synchronize() == IndexSyncCounts(authors_updated=1, posts_removed=1)
    assert len(_post_rows(index)) == 1
    with index.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM posts_fts')) == 1


def test_vanished_body_keeps_only_locked_projection_and_ignores_orphan_marks(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    library.store.save_locked_post(_locked(library))
    index.synchronize()
    _post_file(library, POST_RECORD_FILENAME).unlink()
    orphan = _post_file(library, VIEWER_RECORD_FILENAME)
    before = orphan.read_bytes()
    assert index.synchronize() == IndexSyncCounts(posts_updated=1)
    row = _indexed(index)
    assert row['folder'] is None
    assert row['favorite'] is False
    assert row['post_json_mtime_ns'] is None
    with index.connect() as connection:
        assert not list(connection.scalars(select(IndexMedia.media_id)))
    assert orphan.read_bytes() == before


def test_vanished_post_removes_all_secondary_rows(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    _post_file(library, POST_RECORD_FILENAME).unlink()
    assert index.synchronize() == IndexSyncCounts(posts_removed=1)
    assert _post_rows(index) == []
    with index.connect() as connection:
        assert connection.scalar(select(IndexAuthor.post_count)) == 0
        assert not list(connection.scalars(select(IndexPostTag.post_row_id)))
        assert not list(connection.scalars(select(IndexMedia.media_id)))
        assert connection.scalar(text('SELECT count(*) FROM posts_fts')) == 0


def test_vanished_author_removes_fts_before_deleting_author(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    shutil.rmtree(library.root / 'writer')
    assert index.synchronize() == IndexSyncCounts(posts_removed=1, authors_removed=1)
    assert _post_rows(index) == []
    with index.connect() as connection:
        assert not list(connection.scalars(select(IndexAuthor.author)))
        assert connection.scalar(text('SELECT count(*) FROM posts_fts')) == 0


def test_added_post_has_new_fingerprint_and_counts(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    added = replace(
        library.record, post=replace(library.record.post, id='ijklmnop-second')
    )
    folder = library.store.choose_post_folder(added.post)
    library.store.save_post(folder, added)
    assert index.synchronize() == IndexSyncCounts(posts_updated=1)
    assert _indexed(index, added.post.id)['folder'] == folder
    with index.connect() as connection:
        assert connection.scalar(select(IndexAuthor.post_count)) == 2


def test_moved_folder_preserves_row_identity_and_relocates_media(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    original_id = _indexed(index)['id']
    folder = Path(library.folder)
    renamed = folder.with_name(f'2026-11-09 - Renamed ({POST_ID[:8]})')
    (library.root / folder).rename(library.root / renamed)
    assert index.synchronize() == IndexSyncCounts(posts_updated=1)
    row = _indexed(index)
    assert row['id'] == original_id
    assert row['folder'] == renamed.as_posix()
    assert row['favorite'] is True
    with index.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM posts_fts')) == 1
        assert (
            connection.scalar(
                select(IndexMedia.path).where(IndexMedia.media_id == AUDIO_ID)
            )
            == f'{renamed.as_posix()}/audio/one.mp3'
        )


def test_same_prefix_replacement_selects_overlay_after_decoding(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    library.store.save_locked_post(_locked(library))
    index.synchronize()
    replacement = replace(
        library.record,
        post=replace(
            library.record.post, id='abcdefgh-replacement', title='Replacement body'
        ),
    )
    write_post_record(library.root / library.folder, replacement)
    _post_file(library, VIEWER_RECORD_FILENAME).unlink()
    assert index.synchronize() == IndexSyncCounts(posts_updated=2)
    assert _indexed(index, replacement.post.id)['access'] == PostAccess.open.value
    assert _indexed(index, replacement.post.id)['folder'] == library.folder
    old = _indexed(index)
    assert old['access'] == PostAccess.locked.value
    assert old['folder'] is None


def test_same_prefix_replacement_removes_vanished_full_identity(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    replacement = replace(
        library.record, post=replace(library.record.post, id='abcdefgh-replacement')
    )
    write_post_record(library.root / library.folder, replacement)
    _post_file(library, VIEWER_RECORD_FILENAME).unlink()
    assert index.synchronize() == IndexSyncCounts(posts_updated=1, posts_removed=1)
    assert [row['post_id'] for row in _post_rows(index)] == [replacement.post.id]
    with index.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM posts_fts')) == 1


def test_added_duplicate_alias_fails_without_mutating_index(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    alias = library.root / 'writer' / f'2026-11-09 - Alias ({POST_ID[:8]})'
    _symlink(library.root / library.folder, alias, directory=True)
    with pytest.raises(AmbiguousPostFolderError):
        index.synchronize()
    assert _indexed(index)['folder'] == library.folder


def test_relocated_contained_alias_is_accepted(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    original = library.root / library.folder
    target = library.root / 'source-records'
    original.rename(target)
    _symlink(target, original, directory=True)
    library.record.post.title = 'Changed through alias'
    write_post_record(target, library.record)
    assert index.synchronize() == IndexSyncCounts(posts_updated=1)
    assert _indexed(index)['title'] == 'Changed through alias'


def test_unsafe_source_alias_is_rejected_even_when_bytes_match(
    library: LibraryFixture, index: LibraryIndex, tmp_path: Path
) -> None:
    record = _post_file(library, POST_RECORD_FILENAME)
    external = tmp_path / 'outside.json'
    shutil.copy2(record, external)
    record.unlink()
    _symlink(external, record)
    with pytest.raises(ValueError, match='escapes'):
        index.synchronize()
    assert _indexed(index)['title'] == library.record.post.title


def test_corrupt_changed_source_rolls_back_prior_author_changes(
    library: LibraryFixture, index: LibraryIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    library.store.save_author(AuthorInfo('first', NOW, title='First'))
    index.synchronize()
    library.store.save_author(AuthorInfo('first', NOW, title='Updated first'))
    _post_file(library, POST_RECORD_FILENAME).write_text('{')
    inventory = inventory_sources(library.root)
    monkeypatch.setattr(
        _index_sync,
        'inventory_sources',
        Mock(
            return_value={author: inventory[author] for author in ['first', 'writer']}
        ),
    )
    with pytest.raises(InvalidPostRecordError):
        index.synchronize()
    with index.connect() as connection:
        assert (
            connection.scalar(
                select(IndexAuthor.title).where(IndexAuthor.author == 'first')
            )
            == 'First'
        )
    assert _indexed(index)['title'] == library.record.post.title


def test_corrupt_viewer_keeps_previous_projection_for_retry(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    _post_file(library, VIEWER_RECORD_FILENAME).write_text('{')
    with pytest.raises(InvalidViewerRecordError):
        index.synchronize()
    assert _indexed(index)['favorite'] is True


def test_copied_library_rebuilds_for_new_root(
    library: LibraryFixture, index: LibraryIndex, tmp_path: Path
) -> None:
    copied = tmp_path / 'copied'
    shutil.copytree(library.root, copied)
    other = LibraryIndex(copied)
    assert other.synchronize() == IndexSyncCounts(rebuilt=True)
    assert _indexed(other)['title'] == _indexed(index)['title']


def test_unrecognized_files_and_recordless_viewer_are_ignored(
    library: LibraryFixture, index: LibraryIndex
) -> None:
    (library.root / 'bad author').mkdir()
    (library.root / 'writer' / 'notes.txt').write_text('Unrelated notes')
    folder = library.root / 'writer' / '2026-11-09 - Orphan (ijklmnop)'
    folder.mkdir()
    (folder / VIEWER_RECORD_FILENAME).write_text('Not a supported viewer record')
    assert index.synchronize() == IndexSyncCounts()


def test_fingerprints_describe_bytes_read_after_inventory(
    library: LibraryFixture, index: LibraryIndex, monkeypatch: pytest.MonkeyPatch
) -> None:
    library.record.post.title = 'First change'
    library.store.save_post(library.folder, library.record)
    inventory = inventory_sources(library.root)
    library.record.post.title = 'Newer contents written after inventory'
    library.store.save_post(library.folder, library.record)
    monkeypatch.setattr(_index_sync, 'inventory_sources', Mock(return_value=inventory))
    assert index.synchronize() == IndexSyncCounts(posts_updated=1)
    row = _indexed(index)
    assert row['title'] == library.record.post.title
    assert (
        row['post_json_size']
        == _post_file(library, POST_RECORD_FILENAME).stat().st_size
    )


def test_unchanged_preparation_uses_two_bulk_source_reads_and_no_row_writes(
    index: LibraryIndex,
) -> None:
    trace = Mock()
    event.listen(Engine, 'before_cursor_execute', trace)
    try:
        assert index.synchronize() == IndexSyncCounts()
    finally:
        event.remove(Engine, 'before_cursor_execute', trace)
    statements = [str(call.args[2]).lstrip().upper() for call in trace.call_args_list]
    assert sum('FROM AUTHORS' in statement for statement in statements) == 1
    assert sum('FROM POSTS' in statement for statement in statements) == 1
    mutations = ('INSERT', 'UPDATE', 'DELETE', 'REPLACE', 'CREATE', 'DROP')
    assert not any(statement.startswith(mutations) for statement in statements)
