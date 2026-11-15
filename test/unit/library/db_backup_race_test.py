from contextlib import closing
from pathlib import Path
from sqlite3 import connect
from uuid import UUID, uuid4

import pytest

from boosty_downloader.infrastructure.library import _db_backup
from boosty_downloader.infrastructure.library._db_engine import DatabaseFileIdentity
from boosty_downloader.infrastructure.library._db_errors import (
    UnsupportedLibraryDatabaseError,
)
from boosty_downloader.infrastructure.library._db_schema import SchemaIdentity
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


def _create_rollback_database(path: Path, library_id: UUID) -> None:
    LibraryDatabase.create(path, library_id=library_id).close()
    with closing(connect(path)) as connection:
        connection.execute('PRAGMA journal_mode=DELETE')


@pytest.mark.parametrize('same_uuid', [False, True])
@pytest.mark.parametrize('replacement_phase', ['before-copy', 'after-copy'])
def test_primary_replaced_around_backup_copy_preserves_previous_recovery_point(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replacement_phase: str,
    *,
    same_uuid: bool,
):
    path = tmp_path.resolve() / 'library.db'
    replacement = path.with_name('replacement.db')
    library_id = uuid4()
    replacement_id = library_id if same_uuid else uuid4()
    _create_rollback_database(path, library_id)
    _create_rollback_database(replacement, replacement_id)
    original_bytes = path.read_bytes()
    replacement_bytes = replacement.read_bytes()
    backup = path.with_name('library.db.bak')
    backup.write_bytes(b'previous recovery point')
    backup_modified_ns = backup.stat().st_mtime_ns
    copy_database = _db_backup._copy_database

    def replace_around_copy(
        source: Path,
        destination: Path,
        identity: SchemaIdentity,
        *,
        source_file: DatabaseFileIdentity,
    ) -> None:
        if replacement_phase == 'before-copy':
            replacement.replace(source)
        copy_database(source, destination, identity, source_file=source_file)
        if replacement_phase == 'after-copy':
            replacement.replace(source)

    monkeypatch.setattr(_db_backup, '_copy_database', replace_around_copy)
    with pytest.raises((UnsupportedLibraryDatabaseError, PermissionError)):
        LibraryDatabase.open(
            path,
            writable=True,
            expected_library_id=library_id,
            backup_before_write=True,
        )

    # Windows can refuse replacement while SQLite holds the primary open.
    if replacement.exists():
        assert path.read_bytes() == original_bytes
        assert replacement.read_bytes() == replacement_bytes
    else:
        assert path.read_bytes() == replacement_bytes
    assert backup.read_bytes() == b'previous recovery point'
    assert backup.stat().st_mtime_ns == backup_modified_ns
    assert not list(tmp_path.glob('*.backup'))


def test_same_uuid_replacement_between_file_capture_and_write_lock_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    path = tmp_path.resolve() / 'library.db'
    replacement = path.with_name('replacement.db')
    library_id = uuid4()
    _create_rollback_database(path, library_id)
    _create_rollback_database(replacement, library_id)
    replacement_bytes = replacement.read_bytes()
    backup = path.with_name('library.db.bak')
    backup.write_bytes(b'previous recovery point')
    backup_modified_ns = backup.stat().st_mtime_ns
    capture_file = DatabaseFileIdentity.capture
    replaced = False

    def capture_then_replace(
        _cls: type[DatabaseFileIdentity], target: Path
    ) -> DatabaseFileIdentity:
        nonlocal replaced
        identity = capture_file(target)
        if target == path and not replaced:
            replaced = True
            replacement.replace(target)
        return identity

    monkeypatch.setattr(
        DatabaseFileIdentity, 'capture', classmethod(capture_then_replace)
    )
    with pytest.raises(UnsupportedLibraryDatabaseError, match='file changed'):
        LibraryDatabase.open(
            path,
            writable=True,
            expected_library_id=library_id,
            backup_before_write=True,
        )
    assert replaced
    assert path.read_bytes() == replacement_bytes
    assert backup.read_bytes() == b'previous recovery point'
    assert backup.stat().st_mtime_ns == backup_modified_ns
    assert sorted(item.name for item in tmp_path.iterdir()) == [
        'library.db',
        'library.db.bak',
    ]
