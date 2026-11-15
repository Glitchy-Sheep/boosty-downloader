"""Primary SQLite lifecycle; stored-record ports are composed separately."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from boosty_downloader.infrastructure.library._db_backup import make_migration_backup
from boosty_downloader.infrastructure.library._db_engine import (
    backup_path,
    make_database_engine,
    validate_database_path,
    validate_new_database_path,
)
from boosty_downloader.infrastructure.library._db_errors import (
    LibraryDatabaseError,
    UnsupportedLibraryDatabaseError,
)
from boosty_downloader.infrastructure.library._db_schema import (
    SCHEMA_VERSION,
    SchemaIdentity,
    create_schema,
    inspect_schema,
    migrate_schema,
)
from boosty_downloader.infrastructure.library._db_snapshot import schema_snapshot

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import Generator
    from pathlib import Path
    from types import TracebackType

    from sqlalchemy import Connection, Engine


class LibraryDatabase:
    """
    Own short-lived connections to one canonical database.

    Creation is explicit and refuses existing files. Opening never recreates data.
    Read-only access does not create or migrate a database; SQLite may still use WAL sidecars.
    """

    def __init__(self, path: Path, engine: Engine, identity: SchemaIdentity) -> None:
        self.path = path
        self.engine = engine
        self.identity = identity

    @classmethod
    def create(cls, path: Path, *, library_id: UUID | None = None) -> LibraryDatabase:
        """Initialize a new file; an interrupted initialization remains an error."""
        path = path.absolute()
        validate_new_database_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        validate_new_database_path(path)
        with path.open('xb'):
            pass
        engine = make_database_engine(path, writable=True)
        identity = SchemaIdentity(SCHEMA_VERSION, library_id or uuid4())
        initialized = False
        try:
            _configure_wal(engine)
            with engine.begin() as connection:
                create_schema(connection, identity.library_id)
            initialized = True
        except DatabaseError as error:
            raise _database_error(path, error) from error
        finally:
            if not initialized:
                engine.dispose()
        engine.dispose()
        return cls(
            path, make_database_engine(path, writable=True, identity=identity), identity
        )

    @classmethod
    def open(cls, path: Path, *, writable: bool = False) -> LibraryDatabase:
        """Validate an existing library and back up before a forward migration."""
        path = path.absolute()
        validate_database_path(path)
        if not path.is_file():
            message = f'Primary library database is missing: {path}; restore {backup_path(path)}'
            raise LibraryDatabaseError(message)
        identity = _read_identity(path)
        if not writable and identity.version != SCHEMA_VERSION:
            message = 'The primary library requires a writable schema upgrade'
            raise UnsupportedLibraryDatabaseError(message)
        engine = make_database_engine(
            path, writable=writable, identity=identity, allow_schema_upgrade=writable
        )
        initialized = False
        try:
            if writable:
                _configure_wal(engine)
                identity = _upgrade(path, engine)
            else:
                with engine.connect() as connection:
                    identity = _validate_database(connection)
            initialized = True
        except DatabaseError as error:
            raise _database_error(path, error) from error
        finally:
            if not initialized:
                engine.dispose()
        if writable:
            engine.dispose()
            engine = make_database_engine(path, writable=True, identity=identity)
        return cls(path, engine, identity)

    @contextmanager
    def transaction(self) -> Generator[Session, None, None]:
        """Commit one operation or roll back all of its changes."""
        with Session(self.engine) as session, session.begin():
            yield session

    def close(self) -> None:
        self.engine.dispose()

    def __enter__(self) -> LibraryDatabase:  # noqa: PYI034 - Python 3.10 has no typing.Self
        """Keep the engine available for scoped operations."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Release connection resources without changing saved data."""
        self.close()


def _read_identity(path: Path) -> SchemaIdentity:
    try:
        with schema_snapshot(path) as snapshot:
            return _inspect_snapshot(snapshot)
    except DatabaseError as error:
        raise _database_error(path, error) from error


def _inspect_snapshot(path: Path) -> SchemaIdentity:
    engine = make_database_engine(path, writable=False)
    try:
        with engine.connect() as connection:
            return _validate_database(connection)
    finally:
        engine.dispose()


def _validate_database(connection: Connection) -> SchemaIdentity:
    identity = inspect_schema(connection)
    if list(connection.execute(text('PRAGMA quick_check')).scalars()) != ['ok']:
        message = 'The primary library failed its integrity check; restore its backup'
        raise LibraryDatabaseError(message)
    return identity


def _upgrade(path: Path, engine: Engine) -> SchemaIdentity:
    with engine.begin() as connection:
        identity = _validate_database(connection)
        if identity.version < SCHEMA_VERSION:
            make_migration_backup(path, identity)
            migrate_schema(connection, identity.version)
        return SchemaIdentity(SCHEMA_VERSION, identity.library_id)


def _configure_wal(engine: Engine) -> None:
    with engine.connect() as connection, connection.begin():
        if connection.execute(text('PRAGMA journal_mode')).scalar_one() == 'wal':
            return
    _enable_wal_exclusively(engine)


def _enable_wal_exclusively(engine: Engine) -> None:
    # Keep the validated database locked across the journal-mode transition.
    # Closing this dedicated connection releases EXCLUSIVE mode before backup readers.
    with engine.connect().execution_options(primary_exclusive=True) as connection:
        raw = cast('sqlite3.Connection', connection.connection.driver_connection)
        raw.execute('PRAGMA locking_mode=EXCLUSIVE').close()
        with connection.begin():
            if list(connection.execute(text('PRAGMA quick_check')).scalars()) != ['ok']:
                message = (
                    'The primary library failed its integrity check; restore its backup'
                )
                raise LibraryDatabaseError(message)
        cursor = raw.execute('PRAGMA journal_mode=WAL')
        try:
            if cursor.fetchone() != ('wal',):
                message = 'The primary library could not enable WAL; use --cache-dir on a local disk'
                raise LibraryDatabaseError(message)
        finally:
            cursor.close()


def _database_error(path: Path, error: DatabaseError) -> LibraryDatabaseError:
    if 'locked' in str(error.orig).lower():
        return LibraryDatabaseError(
            f'Library database is locked: {path}. Use --cache-dir on a local disk for network storage.'
        )
    return LibraryDatabaseError(
        f'Cannot read primary library database {path}. Stop other library processes and copy {backup_path(path)} over {path} to restore it.'
    )
