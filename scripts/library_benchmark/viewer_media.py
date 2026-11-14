"""Complete media workload validation and response construction measurements."""

from __future__ import annotations

import gzip
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from boosty_downloader.domain.library import MediaCounts, PostOrder
from boosty_downloader.domain.library_media import (
    LibraryMediaView,
    MediaFilters,
    MediaIdentity,
)
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.viewer.media_mapping import media_page_response
from library_benchmark.measurements import Measurement, measure

if TYPE_CHECKING:
    from collections.abc import Sequence

    from boosty_downloader.domain.library_media import (
        LibraryMediaItem,
        LibraryMediaPage,
    )
    from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

GZIP_LEVEL: Final = 6
EXPECTED_COUNTS: Final = MediaCounts(images=5129, videos=5268, audio=135, files=5125)
EXPECTED_REMOVED: Final = 654


@dataclass(frozen=True, slots=True)
class MediaQuery:
    """One complete reader selection with its reproducible filters."""

    name: str
    view: LibraryMediaView = LibraryMediaView.all
    filters: MediaFilters = field(default_factory=MediaFilters)


MEDIA_QUERIES: Final = (
    MediaQuery('complete_media_all'),
    MediaQuery('complete_media_unseen', filters=MediaFilters(unseen_only=True)),
    MediaQuery('complete_media_favorites', filters=MediaFilters(favorites_only=True)),
    MediaQuery(
        'complete_media_unseen_favorites_oldest',
        filters=MediaFilters(
            unseen_only=True, favorites_only=True, order=PostOrder.oldest
        ),
    ),
    MediaQuery(
        'complete_media_videos_unseen_oldest',
        view=LibraryMediaView.video,
        filters=MediaFilters(unseen_only=True, order=PostOrder.oldest),
    ),
    MediaQuery('complete_media_files', view=LibraryMediaView.file),
)


@dataclass(frozen=True, slots=True)
class MediaQueryResult:
    """Observed selection sizes, including the sample's current viewing marks."""

    query: MediaQuery
    items: int
    posts: int
    counts: MediaCounts
    missing: int
    removed: int


@dataclass(frozen=True, slots=True)
class MediaWorkload:
    """Validated unfiltered sample dimensions across all supported kinds."""

    counts: MediaCounts
    all_items: int
    files_items: int
    downloaded: int
    removed: int


@dataclass(frozen=True, slots=True)
class ResponseSize:
    """UTF-8 response bytes and gzip bytes at the server's compression level."""

    items: int
    posts: int
    json_bytes: int
    gzip_bytes: int
    gzip_level: int = GZIP_LEVEL


@dataclass(frozen=True, slots=True)
class MediaBenchmark:
    """Reader and response measurements with their independently checked workload."""

    workload: MediaWorkload
    queries: tuple[MediaQueryResult, ...]
    response: ResponseSize
    measurements: tuple[Measurement, ...]


def benchmark_media(
    reader: JsonLibraryReader, author: str, *, samples: int, budget_seconds: float
) -> MediaBenchmark:
    """Validate complete results before timing reader calls or response construction."""
    all_page = reader.list_media(author, LibraryMediaView.all, MediaFilters())
    files_page = reader.list_media(author, LibraryMediaView.file, MediaFilters())
    workload = validate_media_workload(all_page, files_page)
    queries = tuple(
        describe_media_query(
            query, reader.list_media(author, query.view, query.filters)
        )
        for query in MEDIA_QUERIES
    )
    measurements = tuple(
        _measure_query(reader, author, query, samples, budget_seconds)
        for query in MEDIA_QUERIES
    )
    return MediaBenchmark(
        workload,
        queries,
        response_size(author, all_page),
        measurements + _measure_response(author, all_page, samples),
    )


def validate_media_workload(
    all_page: LibraryMediaPage,
    files_page: LibraryMediaPage,
    *,
    expected_counts: MediaCounts = EXPECTED_COUNTS,
    expected_removed: int = EXPECTED_REMOVED,
) -> MediaWorkload:
    """Reject incomplete samples, including missing retained downloaded copies."""
    describe_media_query(MediaQuery('all'), all_page)
    describe_media_query(MediaQuery('files', LibraryMediaView.file), files_page)
    items = all_page.items + files_page.items
    counts = _count_kinds(items)
    if counts != expected_counts:
        message = f'Expected media counts {expected_counts}; found {counts}'
        raise ValueError(message)
    if all_page.counts != counts or files_page.counts != counts:
        message = 'Unfiltered media aggregates differ from the complete inventory'
        raise ValueError(message)
    removed = sum(item.entry.removed_at is not None for item in items)
    if removed != expected_removed:
        message = f'Expected {expected_removed} retained removed media; found {removed}'
        raise ValueError(message)
    return MediaWorkload(
        counts, len(all_page.items), len(files_page.items), len(items), removed
    )


def describe_media_query(query: MediaQuery, page: LibraryMediaPage) -> MediaQueryResult:
    """Check materialized rows against counts and the deduplicated post map."""
    _validate_media_query(query, page)
    return MediaQueryResult(
        query,
        len(page.items),
        len(page.posts),
        page.counts,
        page.missing,
        sum(item.entry.removed_at is not None for item in page.items),
    )


def _validate_media_query(query: MediaQuery, page: LibraryMediaPage) -> None:
    identities = {MediaIdentity(item.post_id, item.media_id) for item in page.items}
    if len(identities) != len(page.items):
        message = f'{query.name} contains duplicate media identities'
        raise ValueError(message)
    if set(page.posts) != {item.post_id for item in page.items}:
        message = f'{query.name} has an incomplete or extra shared post entry'
        raise ValueError(message)
    counts = _count_kinds(page.items)
    if _view_count(query.view, page.counts) != len(page.items) or _view_count(
        query.view, counts
    ) != len(page.items):
        message = f'{query.name} does not contain the complete selected media view'
        raise ValueError(message)


def _count_kinds(items: Sequence[LibraryMediaItem]) -> MediaCounts:
    if any(item.entry.status != MediaStatus.downloaded for item in items):
        message = 'A media view contains pieces without a downloaded copy'
        raise ValueError(message)
    kinds = Counter(item.entry.kind for item in items)
    return MediaCounts(
        images=kinds[MediaKind.image],
        videos=kinds[MediaKind.boosty_video] + kinds[MediaKind.external_video],
        audio=kinds[MediaKind.audio],
        files=kinds[MediaKind.file],
    )


def _view_count(view: LibraryMediaView, counts: MediaCounts) -> int:
    match view:
        case LibraryMediaView.all:
            return counts.images + counts.videos + counts.audio
        case LibraryMediaView.image:
            return counts.images
        case LibraryMediaView.video:
            return counts.videos
        case LibraryMediaView.audio:
            return counts.audio
        case LibraryMediaView.file:
            return counts.files


def _measure_query(
    reader: JsonLibraryReader,
    author: str,
    query: MediaQuery,
    samples: int,
    budget_seconds: float,
) -> Measurement:
    return measure(
        query.name,
        lambda: reader.list_media(author, query.view, query.filters),
        samples=samples,
        budget_seconds=budget_seconds,
    )


def serialize_response(author: str, page: LibraryMediaPage) -> bytes:
    """Use the production mapper and JSON serializer, without HTTP transport."""
    return media_page_response(author, page).model_dump_json().encode('utf-8')


def compress_response(payload: bytes) -> bytes:
    """Match the server's default gzip level with a deterministic timestamp."""
    return gzip.compress(payload, compresslevel=GZIP_LEVEL, mtime=0)


def response_size(author: str, page: LibraryMediaPage) -> ResponseSize:
    """Record complete serialized and compressed sizes outside timed operations."""
    payload = serialize_response(author, page)
    return ResponseSize(
        len(page.items), len(page.posts), len(payload), len(compress_response(payload))
    )


def _measure_response(
    author: str, page: LibraryMediaPage, samples: int
) -> tuple[Measurement, ...]:
    return (
        measure(
            'media_response_mapping',
            lambda: media_page_response(author, page),
            samples=samples,
        ),
        measure(
            'media_response_mapping_json',
            lambda: serialize_response(author, page),
            samples=samples,
        ),
        measure(
            'media_response_mapping_json_gzip',
            lambda: compress_response(serialize_response(author, page)),
            samples=samples,
        ),
    )
