from contextlib import closing
from datetime import timedelta, timezone
from pathlib import Path
from sqlite3 import connect
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError, OperationalError, StatementError
from support.library_db import NOW, saved_post

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.stored_post import (
    LineBreak,
    MediaBlock,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    TextBlock,
)
from boosty_downloader.infrastructure.library._db_engine import BUSY_TIMEOUT_SECONDS
from boosty_downloader.infrastructure.library._db_errors import (
    LibraryDatabaseError,
    UnsafeLibraryDatabasePathError,
    UnsupportedLibraryDatabaseError,
)
from boosty_downloader.infrastructure.library._db_models import (
    DbAuthor,
    DbMarks,
    DbMedia,
    DbMediaMarks,
    DbPost,
    LibraryBase,
)
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


def test_create_and_reopen_keep_identity_and_connection_pragmas(tmp_path: Path):
    path = tmp_path.resolve() / 'library.db'
    identity = uuid4()
    with LibraryDatabase.create(path, library_id=identity) as database:
        for _ in range(2):
            with database.engine.connect() as connection:
                assert (
                    connection.execute(text('PRAGMA journal_mode')).scalar_one()
                    == 'wal'
                )
                assert connection.execute(text('PRAGMA synchronous')).scalar_one() == 1
                assert connection.execute(text('PRAGMA foreign_keys')).scalar_one() == 1
                assert connection.execute(
                    text('PRAGMA busy_timeout')
                ).scalar_one() == int(BUSY_TIMEOUT_SECONDS * 1000)
        reflected = inspect(database.engine)
        assert set(LibraryBase.metadata.tables).issubset(reflected.get_table_names())
        for name, table in LibraryBase.metadata.tables.items():
            assert {column.name for column in table.columns} == {
                column['name'] for column in reflected.get_columns(name)
            }
        indexes = {
            item['name']: item['column_names']
            for item in reflected.get_indexes('media')
        }
        assert indexes['ix_media_storage'] == ['status', 'author', 'kind', 'size']
    with LibraryDatabase.open(path) as database:
        assert database.identity.library_id == identity
        assert database.identity.version == 2
    assert not path.with_name('library.db.bak').exists()


def test_full_identity_author_and_id8_collisions_are_independent(tmp_path: Path):
    with LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database:
        with database.transaction() as session:
            session.add_all([DbAuthor(author='alice'), DbAuthor(author='bob')])
            session.flush()
            session.add_all(
                [
                    saved_post(post_id='12345678-first'),
                    saved_post(post_id='12345678-second'),
                    saved_post(author='bob', post_id='12345678-first'),
                ]
            )
        with pytest.raises(IntegrityError), database.transaction() as session:
            session.add(saved_post(post_id='12345678-first'))
        with database.transaction() as session:
            assert len(session.scalars(select(DbPost)).all()) == 3


def test_saved_metadata_body_and_timezone_round_trip_are_independent(tmp_path: Path):
    with LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database:
        with database.transaction() as session:
            session.add(DbAuthor(author='alice'))
            session.flush()
            row = saved_post()
            row.created_at = NOW.astimezone(timezone(timedelta(hours=3)))
            row.blocks = [
                TextBlock([LineBreak()]),
                ParagraphBreak(),
                MediaBlock('image:later'),
            ]
            session.add(row)
        with database.transaction() as session:
            stored = session.scalars(select(DbPost)).one()
            assert stored.created_at == NOW
            assert stored.created_at.tzinfo is timezone.utc
            assert stored.saved_metadata is not None
            assert stored.saved_metadata.created_at == NOW
            assert stored.blocks == [
                TextBlock([LineBreak()]),
                ParagraphBreak(),
                MediaBlock('image:later'),
            ]
            stored.saved_metadata.tags.append('local mutation')
        with database.transaction() as session:
            stored = session.scalars(select(DbPost)).one()
            assert stored.saved_metadata is not None
            assert stored.saved_metadata.tags == []


def test_naive_timestamp_is_rejected(tmp_path: Path):
    with (
        LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database,
        pytest.raises(StatementError, match='timezone-aware'),
        database.transaction() as session,
    ):
        session.add(DbAuthor(author='alice', synced_at=NOW.replace(tzinfo=None)))


def test_locked_overview_can_retain_saved_content_and_independent_marks(tmp_path: Path):
    with LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database:
        with database.transaction() as session:
            session.add(DbAuthor(author='alice'))
            session.flush()
            row = saved_post(title='Saved title')
            row.title = 'Locked title'
            row.access = PostAccess.locked
            row.locked_synced_at = NOW
            session.add(row)
            session.flush()
            row_id = row.id
            session.add(
                DbMedia(
                    post_row_id=row_id,
                    author='alice',
                    media_id='file:retained',
                    kind=MediaKind.file,
                    status=MediaStatus.downloaded,
                    position=7,
                    path='files/copy.txt',
                    size=42,
                    added_at=NOW,
                    removed_at=NOW,
                )
            )
            session.add(DbMarks(post_row_id=row_id, favorite=True, seen_at=NOW))
            session.add_all(
                [
                    DbMediaMarks(
                        post_row_id=row_id, media_id='file:retained', position=12.5
                    ),
                    DbMediaMarks(
                        post_row_id=row_id, media_id='future-kind:absent', position=7
                    ),
                ]
            )
        with database.transaction() as session:
            media = session.scalars(select(DbMedia)).one()
            session.delete(media)
        with database.transaction() as session:
            row = session.get(DbPost, row_id)
            assert row is not None
            assert row.saved_metadata is not None
            assert row.title == 'Locked title'
            assert row.saved_metadata.title == 'Saved title'
            assert row.folder == 'alice/full-id'
            assert len(session.scalars(select(DbMediaMarks)).all()) == 2
            assert session.scalars(select(DbMarks)).one().favorite
            session.delete(row)
        with database.transaction() as session:
            assert session.scalars(select(DbMediaMarks)).all() == []
            assert session.scalars(select(DbMarks)).all() == []


def test_media_author_must_match_owning_post(tmp_path: Path):
    with LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database:
        with database.transaction() as session:
            session.add_all([DbAuthor(author='alice'), DbAuthor(author='bob')])
            session.flush()
            row = saved_post()
            session.add(row)
            session.flush()
            row_id = row.id
        with pytest.raises(IntegrityError), database.transaction() as session:
            session.add(
                DbMedia(
                    post_row_id=row_id,
                    author='bob',
                    media_id='file:x',
                    kind=MediaKind.file,
                    status=MediaStatus.pending,
                    position=0,
                    added_at=NOW,
                )
            )


def test_read_only_open_cannot_write_and_missing_open_cannot_create(tmp_path: Path):
    path = tmp_path.resolve() / 'library.db'
    with pytest.raises(LibraryDatabaseError, match='missing'):
        LibraryDatabase.open(path, writable=True)
    assert list(tmp_path.iterdir()) == []
    LibraryDatabase.create(path).close()
    with (
        LibraryDatabase.open(path) as database,
        pytest.raises(OperationalError, match='readonly'),
        database.transaction() as session,
    ):
        session.add(DbAuthor(author='alice'))


@pytest.mark.parametrize('state', ['garbage', 'empty', 'unrelated', 'future'])
def test_invalid_existing_database_and_previous_backup_stay_untouched(
    tmp_path: Path, state: str
):
    path = tmp_path.resolve() / 'library.db'
    if state == 'future':
        LibraryDatabase.create(path).close()
        with closing(connect(path)) as connection:
            connection.execute('UPDATE meta SET schema_version = 999')
            connection.commit()
    elif state == 'unrelated':
        with closing(connect(path)) as connection:
            connection.execute('CREATE TABLE important (value TEXT)')
    else:
        path.write_bytes(b'not a database' if state == 'garbage' else b'')
    backup = path.with_name('library.db.bak')
    backup.write_bytes(b'previous recovery copy')
    before = {
        file.name: (file.read_bytes(), file.stat().st_mtime_ns)
        for file in tmp_path.iterdir()
    }
    with pytest.raises(LibraryDatabaseError):
        LibraryDatabase.open(path, writable=True)
    after = {
        file.name: (file.read_bytes(), file.stat().st_mtime_ns)
        for file in tmp_path.iterdir()
    }
    assert after == before
    with pytest.raises((FileExistsError, UnsafeLibraryDatabasePathError)):
        LibraryDatabase.create(path)
    assert path.read_bytes() == before[path.name][0]


@pytest.mark.parametrize('suffix', ['', '-wal', '-shm', '-journal', '.bak'])
def test_symlink_database_or_auxiliary_path_is_refused(tmp_path: Path, suffix: str):
    path = tmp_path.resolve() / 'library.db'
    external = tmp_path / 'untouched'
    external.write_bytes(b'private')
    candidate = path.with_name(path.name + suffix)
    try:
        candidate.symlink_to(external)
    except OSError:
        pytest.skip('Symlink creation is unavailable')
    with pytest.raises(UnsafeLibraryDatabasePathError):
        LibraryDatabase.create(path)
    assert external.read_bytes() == b'private'


def test_unknown_schema_error_is_specific(tmp_path: Path):
    path = tmp_path.resolve() / 'library.db'
    LibraryDatabase.create(path).close()
    with closing(connect(path)) as connection:
        connection.execute('UPDATE meta SET schema_version = 3')
        connection.commit()
    with pytest.raises(UnsupportedLibraryDatabaseError, match='version: 3'):
        LibraryDatabase.open(path)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), float('-inf')])
def test_nonfinite_saved_metadata_and_prices_are_refused(tmp_path: Path, value: float):
    with LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database:
        with database.transaction() as session:
            session.add(DbAuthor(author='alice'))
        post = saved_post()
        assert post.saved_metadata is not None
        post.saved_metadata.tier_price_rub = value
        with (
            pytest.raises(StatementError, match='finite'),
            database.transaction() as session,
        ):
            session.add(post)
        post = saved_post()
        post.tier_price_rub = value
        with (
            pytest.raises(StatementError, match='finite'),
            database.transaction() as session,
        ):
            session.add(post)
