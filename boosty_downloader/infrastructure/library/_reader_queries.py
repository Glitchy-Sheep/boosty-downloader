"""Typed index queries and independent domain snapshots for library readers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final, TypeAlias
from unicodedata import category as unicode_category

from sqlalchemy import Integer, Select, and_, func, or_, select, text
from sqlalchemy.orm import Session

from boosty_downloader.domain.library import (
    LibraryAuthor,
    LibraryContentKind,
    PostAccess,
    PostFilters,
    PostOverview,
)
from boosty_downloader.domain.stored_post import AuthorInfo, MediaKind, PostMetadata
from boosty_downloader.infrastructure.library._index_models import (
    IndexAuthor,
    IndexPost,
    IndexPostTag,
)
from boosty_downloader.infrastructure.library.index_projection import fold_search_text

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import ColumnElement, Connection

PostQuery: TypeAlias = Select[IndexPost]

# Continuation marks from sqlite3Fts5UnicodeIsdiacritic in SQLite's unicode61.
# https://github.com/sqlite/sqlite/blob/master/ext/fts5/fts5_unicode2.c
_UNICODE61_DIACRITICS: Final = frozenset(
    '\u0300\u0301\u0302\u0303\u0304\u0306\u0307\u0308\u0309\u030a\u030b\u030c'
    '\u030f\u0311\u031b\u0323\u0324\u0325\u0326\u0327\u0328\u032d\u032e\u0330\u0331'
)


class _RemoteCounter(str, Enum):
    """Boosty content-counter names, distinct from stored media kinds."""

    platform_video = 'ok_video'
    external_video = 'video'
    image = 'image'
    file = 'file'
    audio = 'audio'


_SAVED_KINDS: Final = {
    LibraryContentKind.video: (MediaKind.boosty_video, MediaKind.external_video),
    LibraryContentKind.image: (MediaKind.image,),
    LibraryContentKind.file: (MediaKind.file,),
    LibraryContentKind.audio: (MediaKind.audio,),
}
_REMOTE_KINDS: Final = {
    LibraryContentKind.video: (
        _RemoteCounter.platform_video,
        _RemoteCounter.external_video,
    ),
    LibraryContentKind.image: (_RemoteCounter.image,),
    LibraryContentKind.file: (_RemoteCounter.file,),
    LibraryContentKind.audio: (_RemoteCounter.audio,),
}


@dataclass(frozen=True, slots=True)
class IndexedPostLocation:
    """A known identity, with a folder only when its body was saved."""

    folder: str | None


def read_authors(connection: Connection) -> list[LibraryAuthor]:
    """Load author snapshots with one query and no canonical JSON reads."""
    query = select(IndexAuthor).order_by(IndexAuthor.author)
    with Session(connection) as session:
        return [_author_snapshot(row) for row in session.scalars(query)]


def read_overviews(
    connection: Connection, author: str, filters: PostFilters
) -> list[PostOverview]:
    """Combine all filters in one query with a deterministic newest-first order."""
    query = _posts_query(author, filters)
    with Session(connection) as session:
        return [_post_overview(row) for row in session.scalars(query)]


def read_post_location(
    connection: Connection, author: str, post_id: str
) -> IndexedPostLocation | None:
    """Find one full identity; no prefix or title matching is allowed."""
    query = select(IndexPost.folder).where(
        IndexPost.author == author, IndexPost.post_id == post_id
    )
    row = connection.execute(query).one_or_none()
    if row is None:
        return None
    return IndexedPostLocation(row[0])


def _posts_query(author: str, filters: PostFilters) -> PostQuery:
    query = select(IndexPost).where(IndexPost.author == author)
    if filters.tag is not None:
        query = query.where(_has_tag(filters.tag))
    if filters.kind is not None:
        query = query.where(_has_kind(filters.kind))
    if filters.unseen_only:
        query = query.where(_is_unseen())
    if expression := _search_expression(filters.text):
        matches = (
            text('SELECT rowid FROM posts_fts WHERE posts_fts MATCH :expression')
            .bindparams(expression=expression)
            .columns(rowid=Integer)
        )
        query = query.where(IndexPost.id.in_(matches))
    return query.order_by(IndexPost.created_at.desc(), IndexPost.post_id.desc())


def _has_tag(tag: str) -> ColumnElement[bool]:
    return (
        select(IndexPostTag.post_row_id)
        .where(
            IndexPostTag.post_row_id == IndexPost.id,
            IndexPostTag.tag == tag,
        )
        .exists()
    )


def _has_kind(kind: LibraryContentKind) -> ColumnElement[bool]:
    saved = or_(
        *(
            func.coalesce(IndexPost.current_counts[item.value].as_integer(), 0) > 0
            for item in _SAVED_KINDS[kind]
        )
    )
    remote = or_(
        *(
            func.coalesce(IndexPost.content_counters[item.value].as_integer(), 0) > 0
            for item in _REMOTE_KINDS[kind]
        )
    )
    return or_(
        and_(IndexPost.folder.is_not(None), saved),
        and_(
            IndexPost.folder.is_(None),
            IndexPost.access == PostAccess.locked.value,
            remote,
        ),
    )


def _is_unseen() -> ColumnElement[bool]:
    return and_(
        IndexPost.access == PostAccess.open.value,
        or_(IndexPost.seen_at.is_(None), IndexPost.pieces_added_at > IndexPost.seen_at),
    )


def _search_expression(value: str) -> str:
    """Treat every word as a literal prefix; punctuation alone adds no filter."""
    return ' AND '.join(f'"{word}"*' for word in _search_words(value))


def _search_words(value: str) -> Iterator[str]:
    """Keep combining marks attached so FTS applies its own diacritic rules."""
    word: list[str] = []
    for character in fold_search_text(value):
        category = unicode_category(character)
        is_base = category[0] in {'L', 'N'} or category == 'Co'
        is_combining = character in _UNICODE61_DIACRITICS and bool(word)
        if is_base or is_combining:
            word.append(character)
        elif word:
            yield ''.join(word)
            word.clear()
    if word:
        yield ''.join(word)


def _author_snapshot(row: IndexAuthor) -> LibraryAuthor:
    if row.synced_at is None:
        return LibraryAuthor(row.author)
    info = AuthorInfo(
        author=row.author,
        synced_at=row.synced_at,
        title=row.title,
        owner_name=row.owner_name,
        description=row.description,
        avatar_path=row.avatar_path,
        cover_path=row.cover_path,
        remote_post_count=row.remote_post_count,
    )
    return LibraryAuthor(row.author, info)


def _post_overview(row: IndexPost) -> PostOverview:
    metadata = PostMetadata(
        id=row.post_id,
        author=row.author,
        url=row.url,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
        published_at=row.published_at,
        tags=list(row.tags),
        tier=row.tier,
        tier_price_rub=row.tier_price_rub,
        post_price_rub=row.post_price_rub,
        likes=row.likes,
        comments=row.comments,
        content_counters=dict(row.content_counters),
    )
    return PostOverview(metadata, PostAccess(row.access))
