from contextlib import closing
from pathlib import Path
from sqlite3 import connect

import pytest
from sqlalchemy import text
from support.library_db import previous_database

from boosty_downloader.infrastructure.library import db_store
from boosty_downloader.infrastructure.library._db_errors import (
    UnsupportedLibraryDatabaseError,
)
from boosty_downloader.infrastructure.library._db_schema import SchemaIdentity
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


def _replacement(path: Path, kind: str) -> bytes:
    if kind == 'unrelated':
        with closing(connect(path)) as connection:
            connection.execute('CREATE TABLE valuable(value TEXT)')
            connection.execute("INSERT INTO valuable VALUES ('keep this data')")
            connection.commit()
    else:
        LibraryDatabase.create(path).close()
        with closing(connect(path)) as connection:
            if kind == 'future':
                connection.execute('UPDATE meta SET schema_version=99')
                connection.commit()
            connection.execute('PRAGMA journal_mode=DELETE')
    result = path.read_bytes()
    assert result[18:20] == b'\x01\x01'
    return result


@pytest.mark.parametrize('writable', [False, True])
@pytest.mark.parametrize('kind', ['unrelated', 'future', 'other-library'])
def test_actual_connection_rejects_replacement_before_persistent_pragmas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str, *, writable: bool
):
    path = tmp_path.resolve() / 'library.db'
    LibraryDatabase.create(path).close()
    replacement = path.with_name('replacement.db')
    expected = _replacement(replacement, kind)
    inspect_original = db_store._read_identity

    def inspect_then_replace(target: Path) -> SchemaIdentity:
        identity = inspect_original(target)
        replacement.replace(target)
        return identity

    monkeypatch.setattr(db_store, '_read_identity', inspect_then_replace)
    with pytest.raises(UnsupportedLibraryDatabaseError):
        LibraryDatabase.open(path, writable=writable)
    assert path.read_bytes() == expected
    assert [file.name for file in tmp_path.iterdir()] == ['library.db']


@pytest.mark.parametrize('writable', [False, True])
def test_open_handle_keeps_its_library_identity(tmp_path: Path, *, writable: bool):
    path = tmp_path.resolve() / 'library.db'
    LibraryDatabase.create(path).close()
    replacement = path.with_name('replacement.db')
    expected = _replacement(replacement, 'other-library')
    with LibraryDatabase.open(path, writable=writable) as database:
        replacement.replace(path)
        with (
            pytest.raises(UnsupportedLibraryDatabaseError, match='identity changed'),
            database.engine.connect() as connection,
        ):
            connection.execute(text('SELECT * FROM authors')).all()
    assert path.read_bytes() == expected


@pytest.mark.parametrize(
    'statement',
    [
        'SELECT schema_version FROM meta',
        "UPDATE authors SET title='wrong schema write'",
    ],
)
def test_upgraded_handle_rejects_restored_older_schema(tmp_path: Path, statement: str):
    path = previous_database(tmp_path / 'library.db')
    with LibraryDatabase.open(path, writable=True) as database:
        assert database.identity.version == 2
        with database.transaction() as session:
            assert (
                session.execute(text('SELECT schema_version FROM meta')).scalar_one()
                == 2
            )
        restored = path.with_name('library.db.bak').read_bytes()
        path.write_bytes(restored)
        with (
            pytest.raises(UnsupportedLibraryDatabaseError, match='schema changed'),
            database.transaction() as session,
        ):
            session.execute(text(statement)).all()
    with closing(connect(path)) as connection:
        assert connection.execute('SELECT schema_version FROM meta').fetchone() == (1,)
        assert connection.execute('SELECT title FROM authors').fetchone() == ('Alice',)


def test_lifecycle_accepts_another_completed_forward_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = previous_database(tmp_path / 'library.db')
    inspect_original = db_store._read_identity

    def inspect_then_upgrade(target: Path) -> SchemaIdentity:
        identity = inspect_original(target)
        with monkeypatch.context() as local:
            local.setattr(db_store, '_read_identity', inspect_original)
            LibraryDatabase.open(target, writable=True).close()
        return identity

    monkeypatch.setattr(db_store, '_read_identity', inspect_then_upgrade)
    with (
        LibraryDatabase.open(path, writable=True) as database,
        database.transaction() as session,
    ):
        assert database.identity.version == 2
        assert (
            session.execute(text('SELECT schema_version FROM meta')).scalar_one() == 2
        )
    with closing(connect(path.with_name('library.db.bak'))) as backup:
        assert backup.execute('SELECT schema_version FROM meta').fetchone() == (1,)
