from contextlib import closing
from pathlib import Path
from shutil import copyfile
from sqlite3 import connect

import pytest
from support.library_db import previous_database

from boosty_downloader.infrastructure.library import _db_snapshot
from boosty_downloader.infrastructure.library._db_errors import (
    LibraryDatabaseError,
    UnsafeLibraryDatabasePathError,
    UnsupportedLibraryDatabaseError,
)
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


def _snapshot(directory: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in directory.iterdir()}


def test_future_schema_only_in_wal_is_rejected_without_touching_primary(tmp_path: Path):
    path = tmp_path.resolve() / 'library.db'
    LibraryDatabase.create(path).close()
    with closing(connect(path)) as writer:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        writer.execute('UPDATE meta SET schema_version=99')
        writer.commit()
        assert path.with_name('library.db-wal').stat().st_size > 0
        before = _snapshot(tmp_path)
        with pytest.raises(UnsupportedLibraryDatabaseError, match='version: 99'):
            LibraryDatabase.open(path, writable=True)
        assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('change', ['checkpoint', 'replacement'])
def test_preflight_refuses_unstable_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
):
    path = previous_database(tmp_path / 'library.db')
    copies = 0

    def copy_and_change(source: Path, destination: Path) -> None:
        nonlocal copies
        copyfile(source, destination)
        if source != path:
            return
        copies += 1
        if change == 'replacement':
            replacement = path.with_name('replacement.db')
            copyfile(path, replacement)
            replacement.replace(path)
        else:
            with closing(connect(path)) as writer:
                writer.execute('PRAGMA journal_mode=WAL')
                writer.execute('UPDATE posts SET likes=likes+1')
                writer.commit()
                writer.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    monkeypatch.setattr(_db_snapshot, 'copyfile', copy_and_change)
    with pytest.raises(
        LibraryDatabaseError, match='changed while preparing a stable snapshot'
    ):
        LibraryDatabase.open(path, writable=True)
    assert copies == 3
    assert not path.with_name('library.db.bak').exists()
    with closing(connect(path)) as connection:
        assert connection.execute('SELECT schema_version FROM meta').fetchone() == (1,)


@pytest.mark.parametrize(
    'damage', ['missing-trigger', 'wrong-trigger', 'missing-fts', 'missing-column']
)
def test_current_schema_requires_complete_search_structure(tmp_path: Path, damage: str):
    path = tmp_path.resolve() / 'library.db'
    LibraryDatabase.create(path).close()
    with closing(connect(path)) as connection:
        connection.execute('DROP TRIGGER posts_fts_update')
        if damage == 'wrong-trigger':
            connection.execute(
                'CREATE TRIGGER posts_fts_update AFTER UPDATE ON posts BEGIN SELECT 1; END'
            )
        elif damage == 'missing-fts':
            connection.execute('DROP TABLE posts_fts')
        elif damage == 'missing-column':
            connection.execute('DROP TRIGGER posts_fts_insert')
            connection.execute('ALTER TABLE posts DROP COLUMN title_search')
        connection.commit()
    before = _snapshot(tmp_path)
    with pytest.raises(
        UnsupportedLibraryDatabaseError, match='search schema is incomplete'
    ):
        LibraryDatabase.open(path, writable=True)
    assert _snapshot(tmp_path) == before


def test_shared_primary_inode_is_refused_before_copy(tmp_path: Path):
    path = previous_database(tmp_path / 'library.db')
    alias = path.with_name('shared.db')
    alias.hardlink_to(path)
    before = _snapshot(tmp_path)
    with pytest.raises(UnsafeLibraryDatabasePathError):
        LibraryDatabase.open(path, writable=True)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    'suffix',
    ['-wal', '-shm', '-journal', '.bak', '.bak-wal', '.bak-shm', '.bak-journal'],
)
def test_orphan_auxiliary_files_prevent_fresh_creation(tmp_path: Path, suffix: str):
    path = tmp_path.resolve() / 'library.db'
    path.with_name(path.name + suffix).write_bytes(b'original library state')
    before = _snapshot(tmp_path)
    with pytest.raises(UnsafeLibraryDatabasePathError, match='already exist'):
        LibraryDatabase.create(path)
    assert _snapshot(tmp_path) == before
