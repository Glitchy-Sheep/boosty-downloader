from contextlib import closing
from pathlib import Path
from sqlite3 import connect

import pytest
from sqlalchemy import Connection, select, text
from support.library_db import NOW, previous_database

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.library import _db_backup, db_store
from boosty_downloader.infrastructure.library._db_errors import (
    LibraryDatabaseError,
    UnsupportedLibraryDatabaseError,
)
from boosty_downloader.infrastructure.library._db_models import (
    DbMarks,
    DbMedia,
    DbMediaMarks,
    DbPost,
)
from boosty_downloader.infrastructure.library._db_schema import SchemaIdentity
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


def test_previous_schema_upgrades_and_preserves_canonical_records_and_marks(
    tmp_path: Path,
):
    path = previous_database(tmp_path / 'library.db')
    with (
        LibraryDatabase.open(path, writable=True) as database,
        database.transaction() as session,
    ):
        rows = session.scalars(select(DbPost).order_by(DbPost.id)).all()
        assert [row.post_id for row in rows] == [
            '12345678-full-one',
            '12345678-full-two',
            'locked-only',
        ]
        assert rows[0].saved_metadata is not None
        assert rows[0].saved_metadata.tags == ['trees']
        assert rows[0].first_downloaded_at == NOW
        assert len(rows[0].blocks or []) == 3
        assert rows[1].access is PostAccess.locked
        assert rows[1].title == 'Новый закрытый заголовок'
        assert rows[1].saved_metadata is not None
        assert rows[1].saved_metadata.title == 'Original title'
        assert rows[1].body_text == 'retained body'
        assert rows[2].saved_metadata is None
        assert rows[2].folder is None
        assert rows[2].blocks is None
        assert rows[2].origin is None
        media = session.scalars(select(DbMedia)).one()
        assert media.position == 4
        assert media.status is MediaStatus.downloaded
        assert media.removed_at is not None
        assert media.added_at == NOW
        assert media.path == 'files/saved.txt'
        assert media.size == 42
        assert session.scalars(select(DbMarks)).one().favorite
        mark = session.scalars(select(DbMediaMarks)).one()
        assert mark.media_id == 'future-kind:absent'
        assert mark.position == 12.75
        assert session.execute(
            text("SELECT rowid FROM posts_fts WHERE posts_fts MATCH 'елка AND cafe'")
        ).scalars().all() == [1]
        assert session.execute(
            text("SELECT rowid FROM posts_fts WHERE posts_fts MATCH 'сохраненный'")
        ).scalars().all() == [1]
    with closing(connect(path.with_name('library.db.bak'))) as backup:
        assert backup.execute('PRAGMA quick_check').fetchone() == ('ok',)
        assert backup.execute('SELECT schema_version FROM meta').fetchone() == (1,)
        assert backup.execute('SELECT COUNT(*) FROM posts').fetchone() == (3,)
        assert backup.execute('SELECT media_id FROM media_marks').fetchone() == (
            'future-kind:absent',
        )
        assert not backup.execute(
            "SELECT name FROM sqlite_schema WHERE name='posts_fts'"
        ).fetchall()


def test_read_only_open_refuses_upgrade_without_backup_or_changes(tmp_path: Path):
    path = previous_database(tmp_path / 'library.db')
    before = (path.read_bytes(), path.stat().st_mtime_ns)
    with pytest.raises(
        UnsupportedLibraryDatabaseError, match='writable schema upgrade'
    ):
        LibraryDatabase.open(path)
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert [item.name for item in tmp_path.iterdir()] == ['library.db']


def test_failed_migration_rolls_back_ddl_data_and_version_and_keeps_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = previous_database(tmp_path / 'library.db')

    def fail_migration(connection: Connection, version: int) -> None:
        assert version == 1
        connection.execute(text('ALTER TABLE posts ADD COLUMN accidental TEXT'))
        connection.execute(text("UPDATE posts SET title = 'lost'"))
        connection.execute(text('UPDATE meta SET schema_version = 2'))
        message = 'injected migration failure'
        raise RuntimeError(message)

    monkeypatch.setattr(db_store, 'migrate_schema', fail_migration)
    with pytest.raises(RuntimeError, match='injected migration failure'):
        LibraryDatabase.open(path, writable=True)
    for candidate in [path, path.with_name('library.db.bak')]:
        with closing(connect(candidate)) as connection:
            assert connection.execute('PRAGMA quick_check').fetchone() == ('ok',)
            assert connection.execute('SELECT schema_version FROM meta').fetchone() == (
                1,
            )
            assert connection.execute(
                'SELECT title FROM posts WHERE id=1'
            ).fetchone() == ('Ёлка café',)
            assert 'accidental' not in {
                row[1] for row in connection.execute('PRAGMA table_info(posts)')
            }


def test_failed_backup_preserves_previous_recovery_copy_and_blocks_upgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = previous_database(tmp_path / 'library.db')
    backup = path.with_name('library.db.bak')
    backup.write_bytes(b'existing recovery copy')
    before = (backup.read_bytes(), backup.stat().st_mtime_ns)

    def fail_backup(source: Path, destination: Path, identity: SchemaIdentity) -> None:
        assert source == path
        assert identity.version == 1
        destination.write_bytes(b'incomplete backup')
        message = 'injected disk failure'
        raise OSError(message)

    monkeypatch.setattr(_db_backup, '_copy_database', fail_backup)
    with pytest.raises(OSError, match='injected disk failure'):
        LibraryDatabase.open(path, writable=True)
    assert (backup.read_bytes(), backup.stat().st_mtime_ns) == before
    assert not list(tmp_path.glob('.*.backup'))
    with closing(connect(path)) as connection:
        assert connection.execute('SELECT schema_version FROM meta').fetchone() == (1,)
        assert 'title_search' not in {
            row[1] for row in connection.execute('PRAGMA table_info(posts)')
        }


def test_reopening_current_schema_does_not_rotate_recovery_copy(tmp_path: Path):
    path = previous_database(tmp_path / 'library.db')
    LibraryDatabase.open(path, writable=True).close()
    backup = path.with_name('library.db.bak')
    before = (backup.read_bytes(), backup.stat().st_mtime_ns)
    LibraryDatabase.open(path, writable=True).close()
    assert (backup.read_bytes(), backup.stat().st_mtime_ns) == before


def test_migration_backup_includes_committed_wal_state(tmp_path: Path):
    path = previous_database(tmp_path / 'library.db')
    with closing(connect(path)) as writer:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("UPDATE posts SET title='Committed WAL title' WHERE id=1")
        writer.commit()
        assert path.with_name('library.db-wal').stat().st_size > 0
        LibraryDatabase.open(path, writable=True).close()
    with closing(connect(path.with_name('library.db.bak'))) as backup:
        assert backup.execute('SELECT title FROM posts WHERE id=1').fetchone() == (
            'Committed WAL title',
        )
        assert backup.execute('SELECT schema_version FROM meta').fetchone() == (1,)


def test_live_backup_sidecars_block_rotation_and_migration(tmp_path: Path):
    path = previous_database(tmp_path / 'library.db')
    backup = previous_database(tmp_path / 'library.db.bak')
    with closing(connect(backup)) as backup_reader:
        backup_reader.execute('PRAGMA journal_mode=WAL')
        backup_reader.execute('PRAGMA wal_autocheckpoint=0')
        backup_reader.execute(
            "UPDATE posts SET title='Old backup WAL overlay' WHERE id=1"
        )
        backup_reader.commit()
        before = {
            file.name: file.read_bytes() for file in tmp_path.glob('library.db.bak*')
        }
        with pytest.raises(
            LibraryDatabaseError, match='backup has active SQLite sidecars'
        ):
            LibraryDatabase.open(path, writable=True)
        assert {
            file.name: file.read_bytes() for file in tmp_path.glob('library.db.bak*')
        } == before
        assert backup_reader.execute(
            'SELECT title FROM posts WHERE id=1'
        ).fetchone() == ('Old backup WAL overlay',)
    with closing(connect(path)) as connection:
        assert connection.execute('SELECT schema_version FROM meta').fetchone() == (1,)
        assert connection.execute('SELECT title FROM posts WHERE id=1').fetchone() == (
            'Ёлка café',
        )


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal'])
def test_backup_sidecar_created_during_copy_blocks_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
):
    path = previous_database(tmp_path / 'library.db')
    backup = previous_database(tmp_path / 'library.db.bak')
    before = backup.read_bytes()
    original_copy = _db_backup._copy_database

    def copy_then_create_sidecar(
        source: Path, destination: Path, identity: SchemaIdentity
    ) -> None:
        original_copy(source, destination, identity)
        backup.with_name(backup.name + suffix).write_bytes(b'retained recovery state')

    monkeypatch.setattr(_db_backup, '_copy_database', copy_then_create_sidecar)
    with pytest.raises(LibraryDatabaseError, match='backup has active SQLite sidecars'):
        LibraryDatabase.open(path, writable=True)
    assert backup.read_bytes() == before
    assert (
        backup.with_name(backup.name + suffix).read_bytes()
        == b'retained recovery state'
    )
    with closing(connect(path)) as connection:
        assert connection.execute('SELECT schema_version FROM meta').fetchone() == (1,)


def test_backup_rejects_another_primary_identity(tmp_path: Path):
    path = previous_database(tmp_path / 'library.db')
    identity = db_store._read_identity(path)
    with closing(connect(path)) as connection:
        connection.execute(
            "UPDATE meta SET library_id='20000000-0000-4000-8000-000000000002'"
        )
        connection.commit()
    before = path.read_bytes()
    with pytest.raises(UnsupportedLibraryDatabaseError, match='identity changed'):
        _db_backup._copy_database(path, path.with_name('temporary.backup'), identity)
    assert path.read_bytes() == before
    assert not path.with_name('library.db.bak').exists()
