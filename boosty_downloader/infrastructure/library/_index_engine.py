"""Scoped SQLite connections and filesystem safety for a disposable index."""

from __future__ import annotations

from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING, Final
from urllib.parse import quote

from sqlalchemy import URL, create_engine, event, text
from sqlalchemy.pool import NullPool

from boosty_downloader.infrastructure.library._media_paths import is_link

if TYPE_CHECKING:
    import sqlite3
    from pathlib import Path

    from sqlalchemy import Connection, Engine
    from sqlalchemy.pool import ConnectionPoolEntry

SQLITE_TIMEOUT_SECONDS: Final = 2.0
INDEX_SIDECAR_SUFFIXES: Final = ('-wal', '-shm', '-journal')


class UnsafeIndexPathError(ValueError):
    """An index path would follow a link or modify another filesystem object."""


def validate_index_path(path: Path) -> None:
    """Reject links, non-files and multiply-linked database or sidecar names."""
    for parent in reversed(path.parents):
        _validate_directory(parent)
    for candidate in (
        path,
        *(path.with_name(path.name + suffix) for suffix in INDEX_SIDECAR_SUFFIXES),
    ):
        _validate_file(candidate)


def _validate_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if is_link(info) or not S_ISDIR(info.st_mode):
        message = f'Index parent must be an ordinary directory: {path}'
        raise UnsafeIndexPathError(message)


def _validate_file(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if is_link(info) or not S_ISREG(info.st_mode) or info.st_nlink > 1:
        message = f'Index must be an ordinary unshared file: {path}'
        raise UnsafeIndexPathError(message)


def make_index_engine(path: Path, *, writable: bool) -> Engine:
    """Use one short-lived connection per operation and explicit transactions."""
    database = f'file:{quote(path.as_posix(), safe="/:")}'
    url = URL.create(
        'sqlite+pysqlite',
        database=database,
        query={'mode': 'rwc' if writable else 'ro', 'uri': 'true'},
    )
    engine = create_engine(
        url,
        poolclass=NullPool,
        connect_args={'timeout': SQLITE_TIMEOUT_SECONDS, 'check_same_thread': True},
    )

    @event.listens_for(engine, 'connect')
    def configure(connection: sqlite3.Connection, _record: ConnectionPoolEntry) -> None:
        connection.isolation_level = None
        with connection:
            connection.execute('PRAGMA foreign_keys=ON').close()
            if writable:
                connection.execute('PRAGMA journal_mode=WAL').close()
                connection.execute('PRAGMA synchronous=NORMAL').close()

    @event.listens_for(engine, 'begin')
    def begin(connection: Connection) -> None:
        connection.execute(text('BEGIN IMMEDIATE' if writable else 'BEGIN'))

    return engine
