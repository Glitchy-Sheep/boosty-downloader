"""The disposable index preserves complete projections and canonical records."""

from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
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
    TextBlock,
)
from boosty_downloader.infrastructure.library import index as index_module
from boosty_downloader.infrastructure.library._index_engine import UnsafeIndexPathError
from boosty_downloader.infrastructure.library._index_models import (
    IndexAuthor,
    IndexMedia,
    IndexPost,
    IndexPostTag,
)
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError
from boosty_downloader.infrastructure.library.index import (
    IndexBuildCounts,
    IndexNotPreparedError,
    IndexStatus,
    LibraryIndex,
)
from boosty_downloader.infrastructure.library.index_projection import (
    project_author,
    project_post,
)
from boosty_downloader.infrastructure.library.index_sources import (
    scan_authors,
    scan_posts,
)
from boosty_downloader.infrastructure.library.library_format import (
    LibraryCompatibilityError,
    initialize_library,
)
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from pathlib import Path

    from sqlalchemy import RowMapping

    from boosty_downloader.infrastructure.library.index_projection import PostProjection

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
POST_ID = 'abcdefgh-first'
FILE_ID = 'file:shared'
AUDIO_ID = 'audio:shared'


@dataclass(frozen=True)
class FileSnapshot:
    contents: bytes
    modified_ns: int


@dataclass(frozen=True)
class LibraryFixture:
    root: Path
    store: JsonPostStore
    folder: str
    record: StoredPost


@pytest.fixture
def library(tmp_path: Path) -> LibraryFixture:
    root = tmp_path / 'library'
    initialize_library(root)
    store = JsonPostStore(root)
    record = StoredPost(
        post=PostMetadata(
            id=POST_ID,
            author='writer',
            url=f'https://boosty.to/writer/posts/{POST_ID}',
            title='Всё original title',
            created_at=NOW,
            updated_at=NOW,
            tags=['one', 'two'],
        ),
        sync=PostSync(NOW, NOW),
        blocks=[
            TextBlock([PostDataChunkText.TextFragment('Original searchable body')]),
            MediaBlock(FILE_ID),
            MediaBlock(AUDIO_ID),
        ],
        media={
            FILE_ID: MediaEntry(
                MediaKind.file,
                MediaStatus.downloaded,
                NOW,
                0,
                path='files/one.zip',
                size=7,
            ),
            AUDIO_ID: MediaEntry(
                MediaKind.audio,
                MediaStatus.downloaded,
                NOW,
                1,
                path='audio/one.mp3',
                size=11,
                duration=timedelta(seconds=60),
            ),
        },
    )
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    store.save_author(AuthorInfo('writer', NOW, title='Blog', remote_post_count=10))
    JsonPostMarks(root).save_marks(
        'writer',
        POST_ID,
        PostMarks(
            seen_at=NOW,
            favorite=True,
            positions={AUDIO_ID: PlaybackPosition(12.5, NOW)},
        ),
    )
    return LibraryFixture(root, store, folder, record)


def _post_rows(index: LibraryIndex) -> list[RowMapping]:
    with index.connect() as connection:
        return list(
            connection.execute(
                select(IndexPost).order_by(IndexPost.author, IndexPost.post_id)
            ).mappings()
        )


def _projection(library: LibraryFixture) -> PostProjection:
    author = next(
        source
        for source in scan_authors(library.root)
        if source.author == library.record.post.author
    )
    return project_post(
        next(
            post
            for post in scan_posts(library.root, author)
            if post.post.overview.post.id == POST_ID
        )
    )


def _canonical_snapshot(root: Path) -> dict[Path, FileSnapshot]:
    return {
        path: FileSnapshot(path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob('*')
        if path.is_file() and not path.name.startswith('index.db')
    }


def test_construction_and_missing_status_create_nothing(tmp_path: Path) -> None:
    root = tmp_path / 'absent'
    index = LibraryIndex(root)
    assert not root.exists()
    assert index.status() is IndexStatus.missing
    assert not root.exists()
    with pytest.raises(OperationalError), index.connect():
        pytest.fail('Absent index unexpectedly opened')
    assert not root.exists()


def test_build_restores_sources_marks_and_typed_values(library: LibraryFixture) -> None:
    index = LibraryIndex(library.root)
    before = _canonical_snapshot(library.root)
    assert index.ensure() is IndexStatus.missing
    assert index.status() is IndexStatus.current
    assert index.ensure() is IndexStatus.current
    rows = _post_rows(index)
    assert len(rows) == 1
    assert rows[0]['title'] == library.record.post.title
    assert rows[0]['created_at'] == NOW
    assert rows[0]['seen_at'] == NOW
    assert rows[0]['favorite'] is True
    assert rows[0]['current_counts']['file'] == 1
    assert rows[0]['current_counts']['audio'] == 1
    assert sum(rows[0]['current_counts'].values()) == 2
    with index.connect() as connection:
        media = list(
            connection.execute(
                select(IndexMedia).order_by(IndexMedia.position)
            ).mappings()
        )
        assert [item['media_id'] for item in media] == [FILE_ID, AUDIO_ID]
        assert media[1]['playback_position'] == 12.5
        assert media[1]['finished_at'] == NOW
        assert media[0]['path'] == f'{library.folder}/files/one.zip'
        assert connection.scalar(text('PRAGMA journal_mode')) == 'wal'
        assert connection.scalar(select(IndexAuthor.post_count)) == 1
        assert (
            connection.scalar(
                text("SELECT original_title FROM posts_fts WHERE posts_fts MATCH 'все'")
            )
            == library.record.post.title
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM sqlite_master WHERE name='ix_media_storage'")
            )
            == 1
        )
    assert _canonical_snapshot(library.root) == before


def test_upsert_replaces_tags_media_search_and_author_counts(
    library: LibraryFixture,
) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    library.record.post.title = 'Replacement title'
    library.record.post.tags = ['new', 'new']
    library.record.blocks = [
        TextBlock([PostDataChunkText.TextFragment('Replacement searchable text')]),
        MediaBlock(AUDIO_ID),
    ]
    library.record.media[FILE_ID].removed_at = NOW + timedelta(days=1)
    library.store.save_post(library.folder, library.record)
    index.upsert_post(_projection(library))
    with index.connect() as connection:
        assert connection.scalar(select(IndexPost.title)) == 'Replacement title'
        assert list(connection.scalars(select(IndexPostTag.tag))) == ['new']
        assert (
            connection.scalar(
                text("SELECT count(*) FROM posts_fts WHERE posts_fts MATCH 'original'")
            )
            == 0
        )
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM posts_fts WHERE posts_fts MATCH 'replacement'"
                )
            )
            == 1
        )
        assert list(
            connection.scalars(
                select(IndexMedia.media_id).order_by(IndexMedia.position)
            )
        ) == [AUDIO_ID, FILE_ID]
        counts = connection.scalar(select(IndexPost.current_counts))
        assert counts is not None
        assert counts['audio'] == 1
        assert counts['file'] == 0
    library.store.save_author(AuthorInfo('writer', NOW, title='Renamed blog'))
    index.upsert_author(project_author(next(scan_authors(library.root))))
    with index.connect() as connection:
        assert connection.scalar(select(IndexAuthor.title)) == 'Renamed blog'
        assert connection.scalar(select(IndexAuthor.post_count)) == 1


def test_media_and_posts_keep_full_identity_across_authors(
    library: LibraryFixture,
) -> None:
    for author, post_id in [('writer', 'ijklmnop-second'), ('another', POST_ID)]:
        metadata = replace(library.record.post, author=author, id=post_id)
        record = replace(library.record, post=metadata)
        library.store.save_post(library.store.choose_post_folder(metadata), record)
    index = LibraryIndex(library.root)
    assert index.rebuild() == IndexBuildCounts(authors=2, posts=3)
    with index.connect() as connection:
        assert len(list(connection.execute(select(IndexMedia)))) == 6
        assert len(list(connection.execute(select(IndexPost)))) == 3


def test_locked_overlay_keeps_saved_media_and_locked_only_rows(
    library: LibraryFixture,
) -> None:
    library.store.save_locked_post(
        LockedPost(replace(library.record.post, title='New locked title'), NOW)
    )
    library.store.save_locked_post(
        LockedPost(
            replace(library.record.post, id='locked00-only', title='Locked only'), NOW
        )
    )
    index = LibraryIndex(library.root)
    assert index.rebuild() == IndexBuildCounts(authors=1, posts=2)
    rows = _post_rows(index)
    assert rows[0]['title'] == 'New locked title'
    assert rows[0]['folder'] == library.folder
    assert rows[0]['access'] == 'locked'
    assert rows[0]['favorite'] is True
    assert rows[1]['folder'] is None
    with index.connect() as connection:
        assert connection.scalar(select(IndexAuthor.locked_post_count)) == 2
        assert len(list(connection.execute(select(IndexMedia)))) == 2


def test_remove_post_clears_all_index_rows_without_changing_source(
    library: LibraryFixture,
) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    before = _canonical_snapshot(library.root)
    index.remove_post('writer', POST_ID)
    index.remove_post('writer', POST_ID)
    assert _post_rows(index) == []
    with index.connect() as connection:
        assert list(connection.execute(select(IndexMedia))) == []
        assert list(connection.execute(select(IndexPostTag))) == []
        assert connection.scalar(text('SELECT count(*) FROM posts_fts')) == 0
        assert connection.scalar(select(IndexAuthor.post_count)) == 0
    assert _canonical_snapshot(library.root) == before


def test_schema_mismatch_rebuilds_unknown_prior_tables(library: LibraryFixture) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    with closing(sqlite3.connect(index.path)) as connection, connection:
        connection.execute('UPDATE meta SET schema_version=99')
        connection.execute(
            'CREATE TABLE future_table(id INTEGER PRIMARY KEY, post_id INTEGER REFERENCES posts(id))'
        )
        connection.execute('INSERT INTO future_table VALUES(1, 1)')
    assert index.ensure() is IndexStatus.incompatible
    assert len(_post_rows(index)) == 1
    with index.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM sqlite_master WHERE name='future_table'")
            )
            == 0
        )


def test_another_library_root_rebuilds_the_same_cache(
    library: LibraryFixture, tmp_path: Path
) -> None:
    index = LibraryIndex(library.root, index_path=tmp_path / 'cache' / 'index.db')
    index.ensure()
    other_root = tmp_path / 'other-library'
    initialize_library(other_root)
    other = LibraryIndex(other_root, index_path=index.path)
    assert other.ensure() is IndexStatus.incompatible
    assert _post_rows(other) == []
    assert (
        LibraryIndex(library.root, index_path=index.path).status()
        is IndexStatus.incompatible
    )


def test_corrupt_index_is_rebuilt_without_canonical_changes(
    library: LibraryFixture,
) -> None:
    index = LibraryIndex(library.root)
    index.path.write_bytes(b'not a SQLite database')
    before = _canonical_snapshot(library.root)
    assert index.ensure() is IndexStatus.corrupt
    assert len(_post_rows(index)) == 1
    assert index.status() is IndexStatus.current
    assert _canonical_snapshot(library.root) == before
    assert not list(index.path.parent.glob('.index-rebuild-*'))


def test_rebuild_rollback_keeps_previous_complete_projection(
    library: LibraryFixture,
) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    (library.root / library.folder / 'post.json').write_bytes(b'{broken')
    with pytest.raises(InvalidPostRecordError):
        index.rebuild()
    assert index.status() is IndexStatus.current
    assert _post_rows(index)[0]['title'] == library.record.post.title


def test_failed_first_build_has_no_valid_partial_metadata(
    library: LibraryFixture,
) -> None:
    index = LibraryIndex(library.root)
    (library.root / library.folder / 'post.json').write_bytes(b'{broken')
    with pytest.raises(InvalidPostRecordError):
        index.ensure()
    assert index.status() is IndexStatus.incompatible


def test_database_lock_is_not_treated_as_corruption(
    library: LibraryFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    before = index.path.read_bytes()
    locked = OperationalError(
        'read index', {}, sqlite3.OperationalError('database is locked')
    )
    monkeypatch.setattr(index_module, '_schema_status', Mock(side_effect=locked))
    with pytest.raises(OperationalError) as raised:
        index.ensure()
    assert raised.value is locked
    assert index.path.read_bytes() == before


def test_existing_reader_sees_complete_old_snapshot_during_rebuild(
    library: LibraryFixture,
) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    with index.connect() as reader:
        old_title = reader.scalar(select(IndexPost.title))
        library.record.post.title = 'Updated while reader is open'
        library.store.save_post(library.folder, library.record)
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(index.rebuild).result(
                timeout=10
            ) == IndexBuildCounts(1, 1)
        assert reader.scalar(select(IndexPost.title)) == old_title
    assert _post_rows(index)[0]['title'] == library.record.post.title


@pytest.mark.parametrize('sidecar', ['', '-wal', '-shm', '-journal'])
def test_index_links_are_rejected_without_changing_target(
    library: LibraryFixture, tmp_path: Path, sidecar: str
) -> None:
    index = LibraryIndex(library.root)
    other = tmp_path / 'unrelated'
    other.write_bytes(b'Keep these bytes')
    linked = index.path.with_name(index.path.name + sidecar)
    try:
        linked.symlink_to(other)
    except OSError as error:
        if getattr(error, 'winerror', None) == 1314:
            pytest.skip('Windows account cannot create symbolic links')
        raise
    with pytest.raises(UnsafeIndexPathError):
        index.ensure()
    assert other.read_bytes() == b'Keep these bytes'
    assert linked.is_symlink()


def test_unmarked_old_library_is_refused_before_creating_external_cache(
    tmp_path: Path,
) -> None:
    root = tmp_path / 'old'
    (root / 'another' / '2024-01-01 - Saved (a)').mkdir(parents=True)
    cache = tmp_path / 'cache' / 'index.db'
    with pytest.raises(LibraryCompatibilityError):
        LibraryIndex(root, index_path=cache).ensure()
    assert not cache.parent.exists()


def test_failed_upsert_rolls_back_fts_tags_media_and_post(
    library: LibraryFixture,
) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    projection = _projection(library)
    broken = replace(
        projection,
        metadata=replace(projection.metadata, title='Uncommitted title'),
        folder=None,
    )
    with pytest.raises(ValueError, match='saved post folder'):
        index.upsert_post(broken)
    assert _post_rows(index)[0]['title'] == library.record.post.title
    with index.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM posts_fts WHERE posts_fts MATCH 'original'")
            )
            == 1
        )
        assert len(list(connection.execute(select(IndexMedia)))) == 2
        assert set(connection.scalars(select(IndexPostTag.tag))) == {'one', 'two'}


def test_corrupt_rebuild_failure_preserves_original_file(
    library: LibraryFixture,
) -> None:
    index = LibraryIndex(library.root)
    damaged = b'not a readable database'
    index.path.write_bytes(damaged)
    (library.root / library.folder / 'post.json').write_bytes(b'{broken')
    with pytest.raises(InvalidPostRecordError):
        index.ensure()
    assert index.path.read_bytes() == damaged
    assert index.status() is IndexStatus.corrupt
    assert not list(index.path.parent.glob('.index-rebuild-*'))


def test_cache_path_with_uri_characters_is_not_misinterpreted(
    library: LibraryFixture, tmp_path: Path
) -> None:
    cache = tmp_path / 'Кеш с пробелами #, 100%' / 'index.db'
    index = LibraryIndex(library.root, index_path=cache)
    index.ensure()
    assert cache.is_file()
    assert len(_post_rows(index)) == 1


def test_incompatible_search_table_is_rebuilt(library: LibraryFixture) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    with closing(sqlite3.connect(index.path)) as connection, connection:
        connection.execute('DROP TABLE posts_fts')
        connection.execute(
            'CREATE TABLE posts_fts(title TEXT, body TEXT, original_title TEXT, original_body TEXT)'
        )
    assert index.ensure() is IndexStatus.incompatible
    with index.connect() as connection:
        assert (
            connection.scalar(
                text("SELECT count(*) FROM posts_fts WHERE posts_fts MATCH 'original'")
            )
            == 1
        )


def test_many_readers_use_their_own_connections(library: LibraryFixture) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_post_rows, index) for _ in range(12)]
        results = [future.result() for future in futures]
    assert all(
        len(rows) == 1 and rows[0]['title'] == library.record.post.title
        for rows in results
    )


def test_shared_database_file_is_not_modified(
    library: LibraryFixture, tmp_path: Path
) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    other = tmp_path / 'another-name.db'
    other.hardlink_to(index.path)
    before = other.read_bytes()
    with pytest.raises(UnsafeIndexPathError):
        index.rebuild()
    assert other.read_bytes() == before
    assert index.path.read_bytes() == before


def test_damaged_post_page_is_detected_and_rebuilt(library: LibraryFixture) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    before = _canonical_snapshot(library.root)
    with closing(sqlite3.connect(index.path)) as connection:
        page_size = connection.execute('PRAGMA page_size').fetchone()[0]
        root_page = connection.execute(
            "SELECT rootpage FROM sqlite_master WHERE name='posts'"
        ).fetchone()[0]
        connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    with index.path.open('r+b') as database:
        database.seek((root_page - 1) * page_size)
        database.write(b'\x00')
    assert index.status() is IndexStatus.corrupt
    assert index.ensure() is IndexStatus.corrupt
    assert _post_rows(index)[0]['title'] == library.record.post.title
    assert _canonical_snapshot(library.root) == before


def test_read_connection_rejects_cache_prepared_for_another_library(
    library: LibraryFixture, tmp_path: Path
) -> None:
    index = LibraryIndex(library.root, index_path=tmp_path / 'cache' / 'index.db')
    index.ensure()
    other_root = tmp_path / 'another-library'
    initialize_library(other_root)
    other = LibraryIndex(other_root, index_path=index.path)
    other.ensure()
    with pytest.raises(IndexNotPreparedError, match='ensure'), index.connect():
        pytest.fail('A connection to another library was exposed')
    assert _post_rows(other) == []


@pytest.mark.parametrize(
    'change', ['DROP TABLE meta', 'UPDATE meta SET schema_version=99']
)
def test_read_connection_rejects_missing_or_incompatible_metadata(
    library: LibraryFixture, change: str
) -> None:
    index = LibraryIndex(library.root)
    index.ensure()
    with closing(sqlite3.connect(index.path)) as connection, connection:
        connection.execute(change)
    with pytest.raises(IndexNotPreparedError), index.connect():
        pytest.fail('An incompatible connection was exposed')
    index.upsert_post(_projection(library))
    assert index.status() is IndexStatus.current
    assert len(_post_rows(index)) == 1


def test_incremental_write_rebuilds_another_library_cache(
    library: LibraryFixture, tmp_path: Path
) -> None:
    index = LibraryIndex(library.root, index_path=tmp_path / 'cache' / 'index.db')
    index.ensure()
    other_root = tmp_path / 'another-library'
    initialize_library(other_root)
    other = LibraryIndex(other_root, index_path=index.path)
    other.ensure()
    index.upsert_post(_projection(library))
    assert index.status() is IndexStatus.current
    assert len(_post_rows(index)) == 1
    with pytest.raises(IndexNotPreparedError):
        _post_rows(other)


def test_incremental_write_checks_the_transaction_after_preparation(
    library: LibraryFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = LibraryIndex(library.root, index_path=tmp_path / 'cache' / 'index.db')
    index.ensure()
    other_root = tmp_path / 'another-library'
    initialize_library(other_root)
    other = LibraryIndex(other_root, index_path=index.path)
    other.ensure()
    prepare = index.ensure

    def prepare_then_replace() -> IndexStatus:
        status = prepare()
        other.ensure()
        return status

    monkeypatch.setattr(index, 'ensure', prepare_then_replace)
    with pytest.raises(IndexNotPreparedError):
        index.upsert_post(_projection(library))
    assert other.status() is IndexStatus.current
    assert _post_rows(other) == []


def test_incremental_counts_leave_other_authors_untouched(
    library: LibraryFixture,
) -> None:
    library.store.save_author(AuthorInfo('another', NOW, title='Another author'))
    index = LibraryIndex(library.root)
    index.ensure()
    with closing(sqlite3.connect(index.path)) as connection:
        connection.execute(
            'CREATE TRIGGER untouched_author BEFORE UPDATE OF post_count ON authors '
            "WHEN OLD.author='another' BEGIN "
            "SELECT RAISE(ABORT, 'unrelated author changed'); END"
        )
    index.upsert_post(_projection(library))
    with index.connect() as connection:
        assert (
            connection.scalar(
                select(IndexAuthor.post_count).where(IndexAuthor.author == 'writer')
            )
            == 1
        )
    index.remove_post('writer', POST_ID)
    with index.connect() as connection:
        assert (
            connection.scalar(
                select(IndexAuthor.post_count).where(IndexAuthor.author == 'writer')
            )
            == 0
        )
        assert (
            connection.scalar(
                select(IndexAuthor.post_count).where(IndexAuthor.author == 'another')
            )
            == 0
        )


def test_prior_search_projection_rebuilds_without_changing_canonical_records(
    library: LibraryFixture,
) -> None:
    original = 'a\x00b'
    library.record.post.title = original
    library.store.save_post(library.folder, library.record)
    index = LibraryIndex(library.root)
    index.ensure()
    before = _canonical_snapshot(library.root)
    with closing(sqlite3.connect(index.path)) as connection, connection:
        connection.execute('UPDATE meta SET schema_version=3')
        connection.execute(
            'UPDATE posts_fts SET title=?, original_title=?', (original, original)
        )
    assert index.ensure() is IndexStatus.incompatible
    with index.connect() as connection:
        assert connection.execute(
            text('SELECT title, original_title FROM posts_fts')
        ).one() == ('a b', 'a b')
        assert connection.scalar(select(IndexPost.title)) == original
    assert _canonical_snapshot(library.root) == before
