"""Validated online recovery snapshots, published only after a complete copy."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from enum import IntEnum
from os import close, fsync
from pathlib import Path
from tempfile import mkstemp
from time import monotonic
from typing import cast

from boosty_downloader.infrastructure.library._db_engine import (
    BUSY_TIMEOUT_SECONDS,
    backup_path,
    backup_sidecars,
    make_database_engine,
    validate_database_path,
)
from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library._db_schema import (
    SchemaIdentity,
    inspect_schema,
)


class _BackupLockStatus(IntEnum):
    """SQLite backup lock results, including on Python 3.10."""

    busy = 5
    locked = 6


def make_migration_backup(path: Path, identity: SchemaIdentity) -> None:
    """Copy committed state while another connection reserves the migration write."""
    validate_database_path(path)
    _require_idle_backup(path)
    descriptor, filename = mkstemp(
        prefix=f'.{path.name}.', suffix='.backup', dir=path.parent
    )
    close(descriptor)
    temporary = Path(filename)
    try:
        _copy_database(path, temporary, identity)
        with temporary.open('r+b') as stream:
            fsync(stream.fileno())
        validate_database_path(path)
        _require_idle_backup(path)
        temporary.replace(backup_path(path))
    finally:
        temporary.unlink(missing_ok=True)


def _require_idle_backup(path: Path) -> None:
    backup = backup_path(path)
    for sidecar in backup_sidecars(path):
        if sidecar.exists() or sidecar.is_symlink():
            message = f'Library backup has active SQLite sidecars: {backup}. Close backup readers and preserve or restore that backup before retrying.'
            raise LibraryDatabaseError(message)


def _copy_database(source: Path, destination: Path, identity: SchemaIdentity) -> None:
    engine = make_database_engine(source, writable=False, identity=identity)
    try:
        with (
            engine.connect() as source_connection,
            closing(sqlite3.connect(destination)) as target,
        ):
            if inspect_schema(source_connection) != identity:
                message = 'The primary library changed before its migration backup'
                raise LibraryDatabaseError(message)
            raw = cast(
                'sqlite3.Connection', source_connection.connection.driver_connection
            )
            started = monotonic()

            def progress(status: int, _remaining: int, _total: int) -> None:
                if (
                    status in (_BackupLockStatus.busy, _BackupLockStatus.locked)
                    and monotonic() - started >= BUSY_TIMEOUT_SECONDS
                ):
                    message = (
                        'The primary library backup timed out waiting for SQLite locks'
                    )
                    raise LibraryDatabaseError(message)

            raw.backup(target, pages=256, progress=progress, sleep=0.05)
            if target.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                message = 'The library recovery copy failed its integrity check'
                raise LibraryDatabaseError(message)
    finally:
        engine.dispose()
