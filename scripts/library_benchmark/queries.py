"""Production SQL shapes checked against synthetic source expectations."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Final, TypeAlias, cast

from sqlalchemy import String, case, func, select, text

from boosty_downloader.domain.library import LibraryContentKind, PostAccess, PostFilters
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost
from boosty_downloader.infrastructure.library._reader_queries import (
    posts_query,
)
from boosty_downloader.infrastructure.library._reader_search import search_expression
from library_benchmark.fixture import (
    BENCHMARK_TAG,
    SEARCH_QUERY,
    SEARCH_TEXT,
    FixtureConfig,
    author_name,
    iter_fixture_posts,
)

if TYPE_CHECKING:
    import sqlite3
    from datetime import datetime

    from sqlalchemy import Connection, Executable

    from library_benchmark.fixture import FixturePost

SqlValue: TypeAlias = str | int | float | bytes | None
SqlRow: TypeAlias = tuple[SqlValue, ...]
_SEARCH_LIMIT: Final = 50


class QueryShape(str, Enum):
    """Normalization needed to compare raw rows with semantic expectations."""

    ordinary = 'ordinary'
    storage = 'storage'


@dataclass(frozen=True, slots=True)
class QueryCase:
    """A bound production query and independently expected output columns."""

    name: str
    statement: Executable
    columns: tuple[str, ...]
    expected_rows: tuple[SqlRow, ...]
    shape: QueryShape = QueryShape.ordinary


@dataclass(frozen=True, slots=True)
class QueryRows:
    """Fully consumed DB-API rows, before ORM or domain construction."""

    columns: tuple[str, ...]
    rows: tuple[SqlRow, ...]


@dataclass(frozen=True, slots=True, order=True)
class StorageKey:
    """The viewer combines platform and external video sizes."""

    author: str
    kind: LibraryContentKind


@dataclass(frozen=True, slots=True)
class _ExpectedPost:
    author: str
    post_id: str
    created_at: datetime
    tags: tuple[str, ...]
    locked: bool
    unseen: bool
    video: bool
    matches_text: bool


@dataclass(frozen=True, slots=True)
class _ExpectedLibrary:
    posts: tuple[_ExpectedPost, ...]
    storage: dict[StorageKey, int]


class QueryValidationError(RuntimeError):
    """The measured query did not return its fixture's expected results."""


def execute_query(connection: Connection, query: QueryCase) -> QueryRows:
    """Time SQL execution and all row fetching, without DTO/ORM construction."""
    with connection.execute(query.statement) as result:
        cursor = cast('sqlite3.Cursor', result.cursor)
        return QueryRows(tuple(result.keys()), tuple(cursor.fetchall()))


def verify_query(query: QueryCase, actual: QueryRows) -> None:
    """Validate every measured identity/count/sum outside the timed interval."""
    positions = [actual.columns.index(name) for name in query.columns]
    rows = tuple(tuple(row[position] for position in positions) for row in actual.rows)
    if query.shape is QueryShape.storage:
        rows = _storage_rows(rows)
    if rows != query.expected_rows:
        message = (
            f'{query.name}: expected {len(query.expected_rows)} rows, got {len(rows)}; '
            f'expected prefix {query.expected_rows[:3]!r}, got {rows[:3]!r}'
        )
        raise QueryValidationError(message)


def build_queries(config: FixtureConfig) -> tuple[QueryCase, ...]:
    """Use the production filter builder and typed production index columns."""
    expected = _expected_library(config)
    author = author_name(0)
    posts = [post for post in expected.posts if post.author == author]
    posts.sort(key=lambda post: (post.created_at, post.post_id), reverse=True)
    return (
        _post_list(author, posts),
        _filtered_list(author, posts),
        _months(author, posts),
        _author_counts(expected.posts),
        _search(expected.posts),
        _storage(expected.storage),
        _storage(expected.storage, author=author),
    )


def _post_list(author: str, posts: list[_ExpectedPost]) -> QueryCase:
    return QueryCase(
        'sql_posts_by_date',
        posts_query(author, PostFilters()),
        ('author', 'post_id'),
        tuple((post.author, post.post_id) for post in posts),
    )


def _filtered_list(author: str, posts: list[_ExpectedPost]) -> QueryCase:
    filters = PostFilters(
        kind=LibraryContentKind.video, unseen_only=True, tag=BENCHMARK_TAG
    )
    return QueryCase(
        'sql_video_unseen_tag',
        posts_query(author, filters),
        ('author', 'post_id'),
        tuple(
            (post.author, post.post_id)
            for post in posts
            if post.video and post.unseen and BENCHMARK_TAG in post.tags
        ),
    )


def _months(author: str, posts: list[_ExpectedPost]) -> QueryCase:
    month = func.strftime('%Y-%m', IndexPost.created_at).label('month')
    query = (
        select(month, func.count().label('posts'))
        .where(IndexPost.author == author)
        .group_by(month)
        .order_by(month)
    )
    counts = Counter(post.created_at.strftime('%Y-%m') for post in posts)
    return QueryCase(
        'sql_months', query, ('month', 'posts'), tuple(sorted(counts.items()))
    )


def _author_counts(posts: tuple[_ExpectedPost, ...]) -> QueryCase:
    query = (
        select(
            IndexPost.author,
            func.count().label('posts'),
            func.sum(
                case((IndexPost.access == PostAccess.locked.value, 1), else_=0)
            ).label('locked'),
        )
        .group_by(IndexPost.author)
        .order_by(IndexPost.author)
    )
    counts = Counter(post.author for post in posts)
    locked = Counter(post.author for post in posts if post.locked)
    rows = tuple(
        (author, count, locked[author]) for author, count in sorted(counts.items())
    )
    return QueryCase('sql_author_counts', query, ('author', 'posts', 'locked'), rows)


def _search(posts: tuple[_ExpectedPost, ...]) -> QueryCase:
    query = (
        text(
            'SELECT posts.author, posts.post_id FROM posts_fts '
            'JOIN posts ON posts.id = posts_fts.rowid '
            'WHERE posts_fts MATCH :expression '
            'ORDER BY posts.author, posts.post_id LIMIT :limit'
        )
        .bindparams(expression=search_expression(SEARCH_QUERY), limit=_SEARCH_LIMIT)
        .columns(author=String, post_id=String)
    )
    rows = sorted((post.author, post.post_id) for post in posts if post.matches_text)
    return QueryCase(
        'sql_fts_prefix', query, ('author', 'post_id'), tuple(rows[:_SEARCH_LIMIT])
    )


def _storage(
    expected: dict[StorageKey, int], *, author: str | None = None
) -> QueryCase:
    query = (
        select(
            IndexMedia.author, IndexMedia.kind, func.sum(IndexMedia.size).label('bytes')
        )
        .where(IndexMedia.status == MediaStatus.downloaded.value)
        .group_by(IndexMedia.author, IndexMedia.kind)
    )
    if author is not None:
        query = query.where(IndexMedia.author == author)
    rows = tuple(
        (key.author, key.kind.value, size)
        for key, size in sorted(expected.items())
        if author is None or key.author == author
    )
    name = 'sql_storage_all' if author is None else 'sql_storage_author'
    return QueryCase(name, query, ('author', 'kind', 'bytes'), rows, QueryShape.storage)


def _expected_library(config: FixtureConfig) -> _ExpectedLibrary:
    posts: list[_ExpectedPost] = []
    storage: dict[StorageKey, int] = defaultdict(int)
    for item in iter_fixture_posts(config):
        posts.append(_expected_post(item))
        for entry in item.record.media.values():
            if entry.status is MediaStatus.downloaded:
                key = StorageKey(item.record.post.author, _viewer_kind(entry.kind))
                storage[key] += entry.size or 0
    return _ExpectedLibrary(tuple(posts), dict(storage))


def _expected_post(item: FixturePost) -> _ExpectedPost:
    metadata = item.locked.post if item.locked is not None else item.record.post
    current = [
        entry for entry in item.record.media.values() if entry.removed_at is None
    ]
    seen_at = item.marks.seen_at if item.marks is not None else None
    newest = max(
        (
            entry.added_at
            for entry in item.record.media.values()
            if entry.removed_at is None or entry.status is MediaStatus.downloaded
        ),
        default=None,
    )
    unseen = item.locked is None and (
        seen_at is None or (newest is not None and newest > seen_at)
    )
    return _ExpectedPost(
        metadata.author,
        metadata.id,
        metadata.created_at,
        tuple(metadata.tags),
        item.locked is not None,
        unseen,
        any(
            entry.kind in {MediaKind.boosty_video, MediaKind.external_video}
            for entry in current
        ),
        SEARCH_TEXT.casefold() in metadata.title.casefold(),
    )


def _viewer_kind(kind: MediaKind) -> LibraryContentKind:
    match kind:
        case MediaKind.boosty_video | MediaKind.external_video:
            return LibraryContentKind.video
        case MediaKind.image:
            return LibraryContentKind.image
        case MediaKind.file:
            return LibraryContentKind.file
        case MediaKind.audio:
            return LibraryContentKind.audio


def _storage_rows(rows: tuple[SqlRow, ...]) -> tuple[SqlRow, ...]:
    combined: dict[StorageKey, int] = defaultdict(int)
    for author, kind, size in rows:
        key = StorageKey(str(author), _viewer_kind(MediaKind(str(kind))))
        combined[key] += cast('int', size)
    return tuple(
        (key.author, key.kind.value, size) for key, size in sorted(combined.items())
    )
