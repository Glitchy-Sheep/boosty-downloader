"""Shared database record identity, read sessions and effective tag membership."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from boosty_downloader.infrastructure.library._db_engine import make_database_engine
from boosty_downloader.infrastructure.library._db_models import (
    DbAuthor,
    DbPost,
    DbPostTag,
)
from boosty_downloader.infrastructure.library._db_post_paths import portable_path_key

if TYPE_CHECKING:
    from collections.abc import Generator

    from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


@contextmanager
def read_session(database: LibraryDatabase) -> Generator[Session, None, None]:
    """Read a committed snapshot without acquiring a writer transaction."""
    engine = make_database_engine(
        database.path, writable=False, identity=database.identity
    )
    try:
        with Session(engine) as session, session.begin():
            yield session
    finally:
        engine.dispose()


def require_author_identity(session: Session, author: str) -> None:
    """Reject portable spelling aliases even when the author's folder is absent."""
    key = portable_path_key(author)
    authors = session.scalars(select(DbAuthor.author).where(DbAuthor.author != author))
    if any(portable_path_key(existing) == key for existing in authors):
        message = f'Author spelling aliases an existing library identity: {author}'
        raise ValueError(message)


def ensure_author(session: Session, author: str) -> DbAuthor:
    """Keep an existing author snapshot or create only its identity placeholder."""
    row = session.get(DbAuthor, author)
    if row is None:
        row = DbAuthor(author=author)
        session.add(row)
        session.flush()
    return row


def find_post_row(session: Session, author: str, post_id: str) -> DbPost | None:
    """Look up the complete post identity within its author."""
    return session.scalar(
        select(DbPost).where(DbPost.author == author, DbPost.post_id == post_id)
    )


def synchronize_post_tags(session: Session, row: DbPost) -> None:
    """Mirror distinct effective overview tags without touching saved metadata."""
    existing = {
        tag.tag: tag
        for tag in session.scalars(
            select(DbPostTag).where(DbPostTag.post_row_id == row.id),
        )
    }
    for tag in set(row.tags):
        if existing.pop(tag, None) is None:
            session.add(DbPostTag(post_row_id=row.id, tag=tag))
    for obsolete in existing.values():
        session.delete(obsolete)
