import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from sqlite3 import connect
from uuid import uuid4

import pytest
from sqlalchemy import text
from support.library_db import previous_database

from boosty_downloader.infrastructure.library import _db_backup, _db_snapshot, db_store
from boosty_downloader.infrastructure.library._db_engine import DatabaseFileIdentity
from boosty_downloader.infrastructure.library._db_errors import (
    UnsupportedLibraryDatabaseError,
)
from boosty_downloader.infrastructure.library._db_schema import SchemaIdentity
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


def _contents(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def _start_backup(path: Path) -> None:
    _db_backup.make_library_backup(
        path, SchemaIdentity(2, uuid4()), source_file=DatabaseFileIdentity(0, 0)
    )


def _take_snapshot(path: Path) -> None:
    with _db_snapshot.schema_snapshot(path):
        pass


@pytest.mark.parametrize(
    'prepare',
    [LibraryDatabase.create, LibraryDatabase.open, _start_backup, _take_snapshot],
)
def test_unverified_runtime_is_rejected_before_primary_path_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    prepare: Callable[[Path], object],
):
    path = tmp_path / 'missing' / 'library.db'

    def refuse_path_access(_path: Path) -> None:
        message = 'Primary paths must not be accessed'
        raise AssertionError(message)

    monkeypatch.setattr(sqlite3, 'sqlite_version_info', (3, 50, 6))
    monkeypatch.setattr(db_store, 'validate_new_database_path', refuse_path_access)
    for module in (db_store, _db_backup, _db_snapshot):
        monkeypatch.setattr(module, 'validate_database_path', refuse_path_access)
    with pytest.raises(UnsupportedLibraryDatabaseError, match='unverified'):
        prepare(path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('previous_schema', [False, True])
def test_expected_identity_is_checked_before_backup_or_writable_configuration(
    tmp_path: Path, *, previous_schema: bool
):
    path = tmp_path.resolve() / 'library.db'
    if previous_schema:
        previous_database(path)
    else:
        LibraryDatabase.create(path).close()
    with closing(connect(path)) as connection:
        connection.execute('PRAGMA journal_mode=DELETE')
    backup = path.with_name('library.db.bak')
    backup.write_bytes(b'prior recovery point')
    before = _contents(tmp_path)

    with pytest.raises(UnsupportedLibraryDatabaseError, match='match its marker'):
        LibraryDatabase.open(
            path,
            writable=True,
            expected_library_id=uuid4(),
            backup_before_write=True,
        )

    assert _contents(tmp_path) == before


def test_startup_backup_captures_committed_wal_before_downloader_writes(tmp_path: Path):
    path = tmp_path.resolve() / 'library.db'
    with LibraryDatabase.create(path) as database:
        library_id = database.identity.library_id
    with closing(connect(path)) as writer:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute("INSERT INTO authors (author, title) VALUES ('alice', 'Before')")
        writer.commit()
        assert path.with_name('library.db-wal').stat().st_size > 0

        with LibraryDatabase.open(
            path,
            writable=True,
            expected_library_id=library_id,
            backup_before_write=True,
        ) as database:
            with database.transaction() as session:
                session.execute(text("UPDATE authors SET title='After'"))
            with closing(connect(path.with_name('library.db.bak'))) as backup:
                assert backup.execute('PRAGMA quick_check').fetchone() == ('ok',)
                assert backup.execute('SELECT title FROM authors').fetchone() == (
                    'Before',
                )
        assert writer.execute('SELECT title FROM authors').fetchone() == ('After',)


def test_primary_replaced_after_preflight_is_not_backed_up_or_reconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path.resolve() / 'library.db'
    with LibraryDatabase.create(path) as original:
        library_id = original.identity.library_id
    replacement = path.with_name('replacement.db')
    LibraryDatabase.create(replacement).close()
    with closing(connect(replacement)) as connection:
        connection.execute('PRAGMA journal_mode=DELETE')
    replacement_bytes = replacement.read_bytes()
    backup = path.with_name('library.db.bak')
    backup.write_bytes(b'existing recovery point')
    inspect_original = db_store._read_identity

    def inspect_then_replace(target: Path) -> SchemaIdentity:
        identity = inspect_original(target)
        replacement.replace(target)
        return identity

    monkeypatch.setattr(db_store, '_read_identity', inspect_then_replace)
    with pytest.raises(UnsupportedLibraryDatabaseError, match='identity changed'):
        LibraryDatabase.open(
            path,
            writable=True,
            expected_library_id=library_id,
            backup_before_write=True,
        )
    assert _contents(tmp_path) == {
        'library.db': replacement_bytes,
        'library.db.bak': b'existing recovery point',
    }


def test_startup_and_migration_share_one_pre_upgrade_recovery_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = previous_database(tmp_path / 'library.db')
    backup_versions: list[int] = []
    make_backup = db_store.make_library_backup

    def record_backup(
        source: Path, identity: SchemaIdentity, *, source_file: DatabaseFileIdentity
    ) -> None:
        backup_versions.append(identity.version)
        make_backup(source, identity, source_file=source_file)

    monkeypatch.setattr(db_store, 'make_library_backup', record_backup)
    with LibraryDatabase.open(
        path, writable=True, backup_before_write=True
    ) as database:
        assert database.identity.version == 2
    assert backup_versions == [1]
    with closing(connect(path.with_name('library.db.bak'))) as backup:
        assert backup.execute('SELECT schema_version FROM meta').fetchone() == (1,)
        assert backup.execute('SELECT COUNT(*) FROM posts').fetchone() == (3,)


def test_failed_run_start_backup_preserves_primary_and_previous_recovery_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path.resolve() / 'library.db'
    LibraryDatabase.create(path).close()
    with closing(connect(path)) as connection:
        connection.execute('PRAGMA journal_mode=DELETE')
    path.with_name('library.db.bak').write_bytes(b'existing recovery point')
    before = _contents(tmp_path)

    def fail_copy(
        source: Path,
        target: Path,
        _identity: SchemaIdentity,
        *,
        source_file: DatabaseFileIdentity,
    ) -> None:
        source_file.require_unchanged(source)
        target.write_bytes(b'incomplete copy')
        message = 'injected backup disk failure'
        raise OSError(message)

    monkeypatch.setattr(_db_backup, '_copy_database', fail_copy)
    with pytest.raises(OSError, match='injected backup disk failure'):
        LibraryDatabase.open(path, writable=True, backup_before_write=True)
    assert _contents(tmp_path) == before


def test_read_only_preparation_refuses_backup_without_creating_destination(
    tmp_path: Path,
):
    path = tmp_path / 'missing' / 'library.db'
    with pytest.raises(ValueError, match='requires writable'):
        LibraryDatabase.open(path, backup_before_write=True)
    assert list(tmp_path.iterdir()) == []
