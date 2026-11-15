"""Numbered transactional migrations for a primary, never rebuildable database."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from uuid import UUID

from sqlalchemy import text

from boosty_downloader.infrastructure.library._db_errors import (
    UnsupportedLibraryDatabaseError,
)
from boosty_downloader.infrastructure.library._db_models import fold_search_text
from boosty_downloader.infrastructure.library._db_schema_v1 import SCHEMA_V1

if TYPE_CHECKING:
    from sqlalchemy import Connection

APPLICATION_ID: Final = 0x42444C42
SCHEMA_VERSION: Final = 2
_CANONICAL_TABLES: Final = frozenset(
    {'meta', 'authors', 'posts', 'media', 'post_tags', 'marks', 'media_marks'}
)


@dataclass(frozen=True, slots=True)
class SchemaIdentity:
    """Portable identity and version read before any schema write."""

    version: int
    library_id: UUID


def inspect_schema(connection: Connection) -> SchemaIdentity:
    """Reject unrelated, incomplete and future schemas without repairing them."""
    if connection.execute(text('PRAGMA application_id')).scalar_one() != APPLICATION_ID:
        message = 'This file is not a Boosty primary library database'
        raise UnsupportedLibraryDatabaseError(message)
    tables = set(
        connection.execute(
            text("SELECT name FROM sqlite_schema WHERE type = 'table'")
        ).scalars()
    )
    if not _CANONICAL_TABLES.issubset(tables):
        message = 'The primary library schema is incomplete; restore its backup'
        raise UnsupportedLibraryDatabaseError(message)
    rows = connection.execute(
        text('SELECT id, schema_version, library_id FROM meta')
    ).all()
    if len(rows) != 1 or rows[0].id != 1:
        message = 'The primary library schema identity is invalid'
        raise UnsupportedLibraryDatabaseError(message)
    version = rows[0].schema_version
    if not isinstance(version, int) or not 1 <= version <= SCHEMA_VERSION:
        message = f'Unsupported primary library schema version: {version}'
        raise UnsupportedLibraryDatabaseError(message)
    try:
        identity = UUID(rows[0].library_id)
    except (ValueError, TypeError, AttributeError) as error:
        message = 'The primary library identity is invalid'
        raise UnsupportedLibraryDatabaseError(message) from error
    if version == SCHEMA_VERSION:
        _validate_search_schema(connection)
    return SchemaIdentity(version, identity)


def _validate_search_schema(connection: Connection) -> None:
    definitions = {
        ' '.join(row.sql.split())
        for row in connection.execute(
            text('SELECT sql FROM sqlite_schema WHERE sql IS NOT NULL')
        )
    }
    required = {' '.join(statement.split()) for statement in _FTS_STATEMENTS}
    columns = {row.name for row in connection.execute(text('PRAGMA table_info(posts)'))}
    if not required.issubset(definitions) or not {
        'title_search',
        'body_search',
    }.issubset(columns):
        message = 'The primary library search schema is incomplete; restore its backup'
        raise UnsupportedLibraryDatabaseError(message)


def create_schema(connection: Connection, library_id: UUID) -> None:
    """Create every numbered version in the caller's single transaction."""
    for statement in SCHEMA_V1:
        connection.execute(text(statement))
    connection.execute(text(f'PRAGMA application_id={APPLICATION_ID}'))
    connection.execute(
        text(
            'INSERT INTO meta(id, schema_version, library_id) VALUES (1, 1, :identity)'
        ),
        {'identity': str(library_id)},
    )
    migrate_schema(connection, 1)


def migrate_schema(connection: Connection, version: int) -> None:
    """Advance known versions; transaction ownership belongs to the opener."""
    if version == 1:
        _add_full_text_search(connection)
        connection.execute(text('UPDATE meta SET schema_version = 2 WHERE id = 1'))


def _add_full_text_search(connection: Connection) -> None:
    connection.execute(
        text("ALTER TABLE posts ADD COLUMN title_search TEXT NOT NULL DEFAULT ''")
    )
    connection.execute(
        text("ALTER TABLE posts ADD COLUMN body_search TEXT NOT NULL DEFAULT ''")
    )
    rows = connection.execute(text('SELECT id, title, body_text FROM posts'))
    for row in rows:
        connection.execute(
            text(
                'UPDATE posts SET title_search = :title, body_search = :body WHERE id = :id'
            ),
            {
                'id': row.id,
                'title': fold_search_text(row.title),
                'body': fold_search_text(row.body_text),
            },
        )
    for statement in _FTS_STATEMENTS:
        connection.execute(text(statement))
    connection.execute(
        text(
            'INSERT INTO posts_fts(rowid, title, body) SELECT id, title_search, body_search FROM posts'
        )
    )


_FTS_STATEMENTS: Final = (
    "CREATE VIRTUAL TABLE posts_fts USING fts5(title, body, tokenize='unicode61 remove_diacritics 2')",
    """CREATE TRIGGER posts_fts_insert AFTER INSERT ON posts BEGIN
        INSERT INTO posts_fts(rowid, title, body) VALUES (new.id, new.title_search, new.body_search);
    END""",
    """CREATE TRIGGER posts_fts_update AFTER UPDATE OF id, title_search, body_search ON posts BEGIN
        DELETE FROM posts_fts WHERE rowid = old.id;
        INSERT INTO posts_fts(rowid, title, body) VALUES (new.id, new.title_search, new.body_search);
    END""",
    """CREATE TRIGGER posts_fts_delete AFTER DELETE ON posts BEGIN
        DELETE FROM posts_fts WHERE rowid = old.id;
    END""",
)
