"""Scoped primary-store connections and safe database/sidecar paths."""

from __future__ import annotations

from dataclasses import dataclass
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

from sqlalchemy import URL, create_engine, event, text
from sqlalchemy.pool import NullPool

from boosty_downloader.infrastructure.library._db_errors import (
    UnsafeLibraryDatabasePathError,
    UnsupportedLibraryDatabaseError,
)
from boosty_downloader.infrastructure.library._db_runtime import (
    require_supported_sqlite,
)
from boosty_downloader.infrastructure.library._db_schema import (
    SchemaIdentity,
    inspect_schema,
)
from boosty_downloader.infrastructure.library._media_paths import is_link

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from sqlalchemy import Connection, Engine
    from sqlalchemy.pool import ConnectionPoolEntry

BUSY_TIMEOUT_SECONDS: Final = 2.0
_SIDECAR_SUFFIXES: Final = ('-wal', '-shm', '-journal')


@dataclass(frozen=True, slots=True)
class DatabaseFileIdentity:
    """Bind preparation connections to the same primary file generation."""

    device: int
    inode: int

    @classmethod
    def capture(cls, path: Path) -> DatabaseFileIdentity:
        """Remember the ordinary primary file before acquiring its write lock."""
        validate_database_path(path)
        info = path.lstat()
        return cls(info.st_dev, info.st_ino)

    def require_unchanged(self, path: Path) -> None:
        """Refuse replacement even when the replacement retains the same UUID."""
        try:
            current = self.capture(path)
        except FileNotFoundError:
            current = None
        if current != self:
            message = f'The primary library file changed during preparation: {path}'
            raise UnsupportedLibraryDatabaseError(message)


def validate_database_path(path: Path) -> None:
    """Reject links and shared files before opening any SQLite-owned name."""
    for parent in reversed(path.parents):
        _validate_directory(parent)
    for candidate in (
        path,
        *(path.with_name(path.name + suffix) for suffix in _SIDECAR_SUFFIXES),
    ):
        _validate_file(candidate)
    _validate_file(backup_path(path))
    for candidate in backup_sidecars(path):
        _validate_file(candidate)


def backup_path(path: Path) -> Path:
    """Locate the one rolling recovery copy beside the primary database."""
    return path.with_name(path.name + '.bak')


def backup_sidecars(path: Path) -> list[Path]:
    """Name every SQLite sidecar belonging to the rolling backup."""
    backup = backup_path(path)
    return [backup.with_name(backup.name + suffix) for suffix in _SIDECAR_SUFFIXES]


def validate_new_database_path(path: Path) -> None:
    """Refuse auxiliary files that could belong to a missing primary database."""
    validate_database_path(path)
    candidates = [path.with_name(path.name + suffix) for suffix in _SIDECAR_SUFFIXES]
    candidates.append(backup_path(path))
    candidates.extend(backup_sidecars(path))
    if any(candidate.exists() for candidate in candidates):
        message = f'Primary library auxiliary files already exist beside {path}; restore the existing library instead of creating one'
        raise UnsafeLibraryDatabasePathError(message)


def _validate_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if is_link(info) or not S_ISDIR(info.st_mode):
        message = f'Library database parent must be an ordinary directory: {path}'
        raise UnsafeLibraryDatabasePathError(message)


def _validate_file(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if is_link(info) or not S_ISREG(info.st_mode) or info.st_nlink > 1:
        message = f'Library database must be an ordinary unshared file: {path}'
        raise UnsafeLibraryDatabasePathError(message)


def make_database_engine(
    path: Path,
    *,
    writable: bool,
    identity: SchemaIdentity | None = None,
    allow_schema_upgrade: bool = False,
) -> Engine:
    """Bind transactions to one primary identity without changing journal mode."""
    require_supported_sqlite()
    database = f'file:{quote(path.as_posix(), safe="/:")}'
    engine = create_engine(
        URL.create(
            'sqlite+pysqlite',
            database=database,
            query={'mode': 'rw' if writable else 'ro', 'uri': 'true'},
        ),
        poolclass=NullPool,
        connect_args={'timeout': BUSY_TIMEOUT_SECONDS, 'check_same_thread': True},
    )

    @event.listens_for(engine, 'connect')
    def configure(connection: sqlite3.Connection, _record: ConnectionPoolEntry) -> None:
        validate_database_path(path)
        connection.isolation_level = None
        connection.execute('PRAGMA foreign_keys=ON').close()
        if writable:
            connection.execute('PRAGMA synchronous=NORMAL').close()

    @event.listens_for(engine, 'begin')
    def begin(connection: Connection) -> None:
        if connection.get_execution_options().get('primary_exclusive'):
            connection.execute(text('BEGIN EXCLUSIVE'))
        else:
            connection.execute(text('BEGIN IMMEDIATE' if writable else 'BEGIN'))
        if identity is not None:
            _require_identity(
                connection, identity, allow_schema_upgrade=allow_schema_upgrade
            )

    return engine


def _require_identity(
    connection: Connection, expected: SchemaIdentity, *, allow_schema_upgrade: bool
) -> None:
    actual = inspect_schema(connection)
    if actual.library_id != expected.library_id:
        message = 'The primary library identity changed after opening'
        raise UnsupportedLibraryDatabaseError(message)
    if actual.version == expected.version:
        return
    if allow_schema_upgrade and actual.version > expected.version:
        return
    message = 'The primary library schema changed after opening'
    raise UnsupportedLibraryDatabaseError(message)
