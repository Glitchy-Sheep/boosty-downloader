"""Versioned schema migrations for the post cache database."""

from collections.abc import Callable
from typing import NamedTuple

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .models import Base, PostCacheEntryModel


class Migration(NamedTuple):
    """A versioned schema migration."""

    version: int
    apply: Callable[[Session], None]


# =============================================================================
# Migration Helpers
# =============================================================================


def _column_exists(session: Session, table: str, column: str) -> bool:
    """Check if a column exists in a table."""
    inspector = inspect(session.get_bind())
    columns = {col['name'] for col in inspector.get_columns(table)}
    return column in columns


def _add_column(session: Session, table: str, column: str, definition: str) -> None:
    """Add a column to a table if it doesn't already exist."""
    if not _column_exists(session, table, column):
        session.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {definition}'))


# =============================================================================
# Migration Functions
# =============================================================================


def v1_add_audio_downloaded(session: Session) -> None:
    """Add audio_downloaded column for tracking audio file downloads."""
    _add_column(
        session,
        table=PostCacheEntryModel.__tablename__,
        column=PostCacheEntryModel.audio_downloaded.name,
        definition='BOOLEAN DEFAULT FALSE NOT NULL',
    )


MIGRATIONS: list[Migration] = [
    Migration(version=1, apply=v1_add_audio_downloaded),
]


# =============================================================================
# Migration Runner
# =============================================================================


def apply_migrations(engine: Engine, session: Session) -> None:
    """Apply all pending migrations to bring the database schema up to date."""
    Base.metadata.create_all(engine)

    current_version = _get_current_version(engine, session)

    for migration in MIGRATIONS:
        if migration.version > current_version:
            migration.apply(session)
            session.commit()
            _set_version(session, migration.version)


def _get_current_version(engine: Engine, session: Session) -> int:
    """Get current schema version, or 0 if version table doesn't exist."""
    inspector = inspect(engine)
    if '_schema_version' not in inspector.get_table_names():
        session.execute(text('CREATE TABLE _schema_version (version INTEGER NOT NULL)'))
        session.execute(text('INSERT INTO _schema_version (version) VALUES (0)'))
        session.commit()
        return 0

    result = session.execute(text('SELECT version FROM _schema_version'))
    row = result.fetchone()
    return row[0] if row else 0


def _set_version(session: Session, version: int) -> None:
    """Update the schema version in the database."""
    session.execute(text('UPDATE _schema_version SET version = :v'), {'v': version})
    session.commit()
