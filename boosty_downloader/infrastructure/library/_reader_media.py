"""Indexed media lists and aggregates from the caller's single read snapshot."""

from __future__ import annotations

from datetime import datetime, timedelta
from math import isfinite
from typing import TYPE_CHECKING, NamedTuple, TypeAlias

from sqlalchemy import Select, and_, case, func, or_, select

from boosty_downloader.domain.library import MediaCounts, PostOrder
from boosty_downloader.domain.library_marks import PlaybackPosition
from boosty_downloader.domain.library_media import (
    LibraryMediaItem,
    LibraryMediaPage,
    LibraryMediaPost,
    LibraryMediaView,
    MediaFilters,
)
from boosty_downloader.domain.stored_post import MediaEntry, MediaKind, MediaStatus
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost
from boosty_downloader.infrastructure.library._record_validation import (
    require_nonnegative,
    validate_relative_file_path,
)

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement, Connection

_MediaQuery: TypeAlias = Select[
    IndexMedia, str | None, datetime, str, str | None, datetime | None, bool
]


class _IndexedMediaRow(NamedTuple):
    """Only the columns needed for a piece and its owning post metadata."""

    author: str
    post_id: str
    media_id: str
    kind: str
    position: int
    path: str | None
    thumbnail_path: str | None
    preview_path: str | None
    title: str | None
    filename: str | None
    artist: str | None
    size: int | None
    duration: float | None
    width: int | None
    height: int | None
    added_at: datetime
    removed_at: datetime | None
    playback_position: float | None
    finished_at: datetime | None
    folder: str | None
    created_at: datetime
    post_title: str
    cover_path: str | None
    seen_at: datetime | None
    favorite: bool


class _MediaTotals(NamedTuple):
    """Downloaded and current missing counts for a supported inventory kind."""

    kind: str
    downloaded: int
    missing: int


def read_media(
    connection: Connection, author: str, view: LibraryMediaView, filters: MediaFilters
) -> LibraryMediaPage:
    """Materialize one complete view and all filtered view counts without file I/O."""
    query = _media_query(author, view, filters)
    selected = query.with_only_columns(
        *(query.selected_columns[name] for name in _IndexedMediaRow._fields),
        maintain_column_froms=True,
    )
    items: list[LibraryMediaItem] = []
    posts: dict[str, LibraryMediaPost] = {}
    for indexed in connection.execute(selected):
        row = _IndexedMediaRow._make(indexed)
        items.append(_media_item(row))
        if row.post_id not in posts:
            posts[row.post_id] = _media_post(row)
    totals = _read_totals(connection, author, filters)
    missing = sum(row.missing for row in totals if row.kind in _view_kinds(view))
    return LibraryMediaPage(items, posts, _media_counts(totals), missing)


def _media_query(
    author: str, view: LibraryMediaView, filters: MediaFilters
) -> _MediaQuery:
    query = (
        select(
            IndexMedia,
            IndexPost.folder,
            IndexPost.created_at,
            IndexPost.title.label('post_title'),
            IndexPost.cover_path,
            IndexPost.seen_at,
            IndexPost.favorite,
        )
        .join(IndexPost, IndexPost.id == IndexMedia.post_row_id)
        .where(
            *_media_predicates(author, filters),
            IndexMedia.kind.in_(_view_kinds(view)),
            IndexMedia.status == MediaStatus.downloaded.value,
        )
    )
    return _ordered_media_query(query, filters.order).order_by(
        IndexMedia.position.asc(), IndexMedia.media_id.asc()
    )


def _ordered_media_query(query: _MediaQuery, order: PostOrder) -> _MediaQuery:
    query = query.order_by(IndexMedia.removed_at.is_not(None).asc())
    if order is PostOrder.oldest:
        return query.order_by(IndexPost.created_at.asc(), IndexPost.post_id.asc())
    return query.order_by(IndexPost.created_at.desc(), IndexPost.post_id.desc())


def _media_predicates(author: str, filters: MediaFilters) -> list[ColumnElement[bool]]:
    predicates = [IndexMedia.author == author]
    if filters.favorites_only:
        predicates.append(IndexPost.favorite.is_(True))
    if filters.unseen_only:
        predicates.extend(
            [
                IndexMedia.finished_at.is_(None),
                or_(
                    IndexPost.seen_at.is_(None),
                    IndexMedia.added_at > IndexPost.seen_at,
                ),
            ]
        )
    return predicates


def _view_kinds(view: LibraryMediaView) -> tuple[MediaKind, ...]:
    match view:
        case LibraryMediaView.all:
            return (
                MediaKind.image,
                MediaKind.boosty_video,
                MediaKind.external_video,
                MediaKind.audio,
            )
        case LibraryMediaView.video:
            return (MediaKind.boosty_video, MediaKind.external_video)
        case LibraryMediaView.image:
            return (MediaKind.image,)
        case LibraryMediaView.audio:
            return (MediaKind.audio,)
        case LibraryMediaView.file:
            return (MediaKind.file,)


def _read_totals(
    connection: Connection, author: str, filters: MediaFilters
) -> list[_MediaTotals]:
    downloaded = IndexMedia.status == MediaStatus.downloaded.value
    missing = and_(
        IndexMedia.removed_at.is_(None),
        IndexMedia.status.in_(
            [
                state.value
                for state in MediaStatus
                if state is not MediaStatus.downloaded
            ]
        ),
    )
    query = (
        select(
            IndexMedia.kind,
            func.sum(case((downloaded, 1), else_=0)),
            func.sum(case((missing, 1), else_=0)),
        )
        .join(IndexPost, IndexPost.id == IndexMedia.post_row_id)
        .where(
            *_media_predicates(author, filters), IndexMedia.kind.in_(list(MediaKind))
        )
        .group_by(IndexMedia.kind)
    )
    return [_MediaTotals._make(row) for row in connection.execute(query)]


def _media_counts(totals: list[_MediaTotals]) -> MediaCounts:
    counts = {row.kind: row.downloaded for row in totals}
    return MediaCounts(
        images=counts.get(MediaKind.image, 0),
        videos=counts.get(MediaKind.boosty_video, 0)
        + counts.get(MediaKind.external_video, 0),
        files=counts.get(MediaKind.file, 0),
        audio=counts.get(MediaKind.audio, 0),
    )


def _media_item(row: _IndexedMediaRow) -> LibraryMediaItem:
    if row.folder is None or row.path is None or row.size is None:
        message = 'Downloaded media requires a post folder, file path and recorded size'
        raise ValueError(message)
    _validate_media_numbers(row)
    _library_path(row.folder, row.author)
    return LibraryMediaItem(
        row.post_id,
        row.created_at,
        row.folder,
        row.media_id,
        _media_entry(row, row.folder),
        _playback(row),
        _library_path(row.thumbnail_path, row.author),
    )


def _media_entry(row: _IndexedMediaRow, folder: str) -> MediaEntry:
    return MediaEntry(
        kind=MediaKind(row.kind),
        status=MediaStatus.downloaded,
        added_at=row.added_at,
        position=row.position,
        removed_at=row.removed_at,
        path=_post_relative_path(row.path, folder),
        preview_path=_post_relative_path(row.preview_path, folder),
        size=row.size,
        title=row.title,
        filename=row.filename,
        artist=row.artist,
        duration=_media_duration(row.duration),
        width=row.width,
        height=row.height,
    )


def _validate_media_numbers(row: _IndexedMediaRow) -> None:
    integers = {
        'size': row.size,
        'position': row.position,
        'width': row.width,
        'height': row.height,
    }
    for name, value in integers.items():
        _validate_number(value, name, integer=True)
    _validate_number(row.duration, 'duration')
    _validate_number(row.playback_position, 'playback_position')


def _validate_number(value: object, name: str, *, integer: bool = False) -> None:
    if value is None:
        return
    if integer and not isinstance(value, int):
        message = f'Indexed media {name} must be an integer'
        raise ValueError(message)
    if not isinstance(value, (int, float)) or not isfinite(value):
        message = f'Indexed media {name} must be finite'
        raise ValueError(message)
    require_nonnegative(**{name: value})


def _media_duration(seconds: float | None) -> timedelta | None:
    if seconds is None:
        return None
    try:
        return timedelta(seconds=seconds)
    except OverflowError as error:
        message = 'Indexed media duration is outside the supported range'
        raise ValueError(message) from error


def _media_post(row: _IndexedMediaRow) -> LibraryMediaPost:
    return LibraryMediaPost(
        row.post_title,
        _library_path(row.cover_path, row.author),
        row.seen_at,
        row.favorite,
    )


def _playback(row: _IndexedMediaRow) -> PlaybackPosition | None:
    if row.playback_position is None and row.finished_at is None:
        return None
    return PlaybackPosition(row.playback_position or 0.0, row.finished_at)


def _library_path(path: str | None, author: str) -> str | None:
    validate_relative_file_path(path, 'indexed library path')
    if path is not None and not path.startswith(f'{author}/'):
        message = 'Indexed path must belong to its author'
        raise ValueError(message)
    return path


def _post_relative_path(path: str | None, folder: str) -> str | None:
    if path is None:
        return None
    validate_relative_file_path(path, 'indexed media path')
    path_parts = path.split('/')
    folder_parts = folder.split('/')
    if path_parts[: len(folder_parts)] != folder_parts:
        message = 'Indexed media path must belong to its post folder'
        raise ValueError(message)
    relative = '/'.join(path_parts[len(folder_parts) :])
    validate_relative_file_path(relative, 'post-relative media path')
    return relative
