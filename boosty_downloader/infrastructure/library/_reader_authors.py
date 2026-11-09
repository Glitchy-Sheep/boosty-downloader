"""Indexed author metadata, post totals, retained storage and exact tag counts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from boosty_downloader.domain.library import (
    AuthorCounts,
    LibraryAuthor,
    MediaStorage,
    PostAccess,
    TagCount,
)
from boosty_downloader.domain.stored_post import AuthorInfo, MediaKind, MediaStatus
from boosty_downloader.infrastructure.library._index_models import (
    IndexAuthor,
    IndexMedia,
    IndexPost,
    IndexPostTag,
)
from boosty_downloader.infrastructure.library._reader_predicates import is_unseen

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement, Connection


def read_authors(connection: Connection) -> list[LibraryAuthor]:
    """Load sorted snapshots with grouped totals independent of author count."""
    counts = _read_counts(connection)
    storage = _read_storage(connection)
    with Session(connection) as session:
        return [
            LibraryAuthor(
                row.author,
                _author_info(row),
                counts.get(row.author, AuthorCounts()),
                storage.get(row.author, MediaStorage()),
            )
            for row in session.scalars(select(IndexAuthor).order_by(IndexAuthor.author))
        ]


def read_author(connection: Connection, author: str) -> LibraryAuthor | None:
    """Load one author and restrict its aggregates to the requested identity."""
    with Session(connection) as session:
        row = session.get(IndexAuthor, author)
        if row is None:
            return None
        return LibraryAuthor(
            row.author,
            _author_info(row),
            _read_counts(connection, author).get(author, AuthorCounts()),
            _read_storage(connection, author).get(author, MediaStorage()),
        )


def has_author(connection: Connection, author: str) -> bool:
    """Check the author identity without reading posts or media."""
    query = select(IndexAuthor.author).where(IndexAuthor.author == author)
    return connection.scalar(query) is not None


def read_tags(connection: Connection, author: str) -> list[TagCount]:
    """Count distinct posts per exact tag, ordered by the stored tag value."""
    query = (
        select(IndexPostTag.tag, func.count(func.distinct(IndexPostTag.post_row_id)))
        .join(IndexPost, IndexPost.id == IndexPostTag.post_row_id)
        .where(IndexPost.author == author)
        .group_by(IndexPostTag.tag)
        .order_by(IndexPostTag.tag)
    )
    return [TagCount(tag, count) for tag, count in connection.execute(query)]


def _read_counts(
    connection: Connection, author: str | None = None
) -> dict[str, AuthorCounts]:
    query = select(
        IndexPost.author,
        func.count(),
        _count_if(IndexPost.access == PostAccess.locked.value),
        _count_if(is_unseen()),
        _count_if(IndexPost.favorite.is_(True)),
    ).group_by(IndexPost.author)
    if author is not None:
        query = query.where(IndexPost.author == author)
    return {
        name: AuthorCounts(posts, locked, unseen, favorites)
        for name, posts, locked, unseen, favorites in connection.execute(query)
    }


def _count_if(predicate: ColumnElement[bool]) -> ColumnElement[int]:
    return func.sum(case((predicate, 1), else_=0))


def _read_storage(
    connection: Connection, author: str | None = None
) -> dict[str, MediaStorage]:
    query = (
        select(
            IndexMedia.author,
            _storage_bytes(MediaKind.image),
            _storage_bytes(MediaKind.boosty_video, MediaKind.external_video),
            _storage_bytes(MediaKind.file),
            _storage_bytes(MediaKind.audio),
        )
        .where(
            IndexMedia.status == MediaStatus.downloaded.value,
            IndexMedia.size.is_not(None),
        )
        .group_by(IndexMedia.author)
    )
    if author is not None:
        query = query.where(IndexMedia.author == author)
    return {
        name: MediaStorage(images, videos, files, audio)
        for name, images, videos, files, audio in connection.execute(query)
    }


def _storage_bytes(*kinds: MediaKind) -> ColumnElement[int]:
    return func.sum(
        case(
            (IndexMedia.kind.in_([kind.value for kind in kinds]), IndexMedia.size),
            else_=0,
        )
    )


def _author_info(row: IndexAuthor) -> AuthorInfo | None:
    if row.synced_at is None:
        return None
    return AuthorInfo(
        author=row.author,
        synced_at=row.synced_at,
        title=row.title,
        owner_name=row.owner_name,
        description=row.description,
        avatar_path=row.avatar_path,
        cover_path=row.cover_path,
        remote_post_count=row.remote_post_count,
    )
