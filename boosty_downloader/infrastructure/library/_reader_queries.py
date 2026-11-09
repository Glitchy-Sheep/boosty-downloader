"""Typed index queries and independent post snapshots for library readers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias, cast

from sqlalchemy import (
    Integer,
    Select,
    String,
    column,
    func,
    literal,
    literal_column,
    select,
    table,
)
from sqlalchemy.orm import Session

from boosty_downloader.domain.library import (
    MediaCounts,
    MonthCount,
    PostAccess,
    PostFilters,
    PostList,
    PostOrder,
    PostOverview,
    PostRow,
)
from boosty_downloader.domain.stored_post import MediaKind, PostMetadata
from boosty_downloader.infrastructure.library._index_models import IndexPost
from boosty_downloader.infrastructure.library._reader_predicates import (
    RemoteCounter,
    post_predicates,
)
from boosty_downloader.infrastructure.library._reader_search import (
    HIT_END,
    HIT_START,
    search_expression,
)
from boosty_downloader.infrastructure.library._reader_snippets import search_match

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement, Connection

    from boosty_downloader.domain.library import SearchMatch

PostQuery: TypeAlias = Select[IndexPost, str | None, str | None, str | None, str | None]
_FTS = table(
    'posts_fts',
    column('rowid', Integer),
    column('original_title', String),
    column('original_body', String),
)


@dataclass(frozen=True, slots=True)
class IndexedPostLocation:
    """A known identity, with a folder only when its body was saved."""

    folder: str | None


def read_posts(connection: Connection, author: str, filters: PostFilters) -> PostList:
    """Read filtered post rows and derive the matching month totals without extra SQL."""
    with Session(connection) as session:
        rows = [
            _post_row(post, _search_match(title, body, original_title, original_body))
            for post, title, body, original_title, original_body in session.execute(
                posts_query(author, filters)
            )
        ]
    counts = Counter(_post_month(row) for row in rows)
    return PostList(
        rows, [MonthCount(month, count) for month, count in counts.items()], len(rows)
    )


def _post_month(row: PostRow) -> str:
    created = row.overview.post.created_at
    return f'{created.year:04d}-{created.month:02d}'


def posts_query(author: str, filters: PostFilters) -> PostQuery:
    """Build the full ordered selection; with_only_columns(IndexPost.id) selects its IDs."""
    query = _search_query(search_expression(filters.text)).where(
        *post_predicates(author, filters)
    )
    if filters.order is PostOrder.oldest:
        return query.order_by(IndexPost.created_at.asc(), IndexPost.post_id.asc())
    return query.order_by(IndexPost.created_at.desc(), IndexPost.post_id.desc())


def _search_query(expression: str) -> PostQuery:
    if not expression:
        empty = cast('ColumnElement[str | None]', literal(None, String))
        return select(IndexPost, empty, empty, empty, empty)
    return (
        select(
            IndexPost,
            func.highlight(literal_column('posts_fts'), 0, HIT_START, HIT_END),
            func.highlight(literal_column('posts_fts'), 1, HIT_START, HIT_END),
            _FTS.c.original_title,
            _FTS.c.original_body,
        )
        .join(_FTS, _FTS.c.rowid == IndexPost.id)
        .where(literal_column('posts_fts').match(expression))
    )


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


def _search_match(
    title: str | None,
    body: str | None,
    original_title: str | None,
    original_body: str | None,
) -> SearchMatch | None:
    if title is None or body is None or original_title is None or original_body is None:
        return None
    return search_match(title, body, original_title, original_body)


def _post_row(row: IndexPost, match: SearchMatch | None) -> PostRow:
    return PostRow(
        overview=_post_overview(row),
        cover_path=row.cover_path,
        counts=_media_counts(row),
        missing_media=_missing_media(row),
        seen_at=row.seen_at,
        favorite=row.favorite,
        pieces_added_at=row.pieces_added_at,
        match=match,
    )


def _missing_media(row: IndexPost) -> int:
    if row.folder is None:
        return 0
    return sum(row.current_counts.values()) - sum(row.downloaded_counts.values())


def _media_counts(row: IndexPost) -> MediaCounts:
    if row.folder is None:
        counts = row.content_counters
        return MediaCounts(
            counts.get(RemoteCounter.image.value, 0),
            counts.get(RemoteCounter.platform_video.value, 0)
            + counts.get(RemoteCounter.external_video.value, 0),
            counts.get(RemoteCounter.file.value, 0),
            counts.get(RemoteCounter.audio.value, 0),
        )
    counts = row.current_counts
    return MediaCounts(
        counts.get(MediaKind.image.value, 0),
        counts.get(MediaKind.boosty_video.value, 0)
        + counts.get(MediaKind.external_video.value, 0),
        counts.get(MediaKind.file.value, 0),
        counts.get(MediaKind.audio.value, 0),
    )


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
