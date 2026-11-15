"""Benchmark preconditions and complete response bytes without timing thresholds."""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from benchmark_viewer_queries import PostWorkload, ViewerBenchmark, report_data
from library_benchmark.measurements import Measurement
from library_benchmark.viewer_media import (
    MediaBenchmark,
    MediaQuery,
    compress_response,
    describe_media_query,
    response_size,
    serialize_response,
    validate_media_workload,
)

from boosty_downloader.domain.library import MediaCounts
from boosty_downloader.domain.library_media import (
    LibraryMediaItem,
    LibraryMediaPage,
    LibraryMediaPost,
    LibraryMediaView,
)
from boosty_downloader.domain.stored_post import MediaEntry, MediaKind, MediaStatus
from boosty_downloader.viewer.api_models import MediaPage

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
_COUNTS = MediaCounts(images=1, videos=2, audio=1, files=1)


@dataclass(frozen=True, slots=True)
class MediaPages:
    all: LibraryMediaPage
    files: LibraryMediaPage


def _item(kind: MediaKind) -> LibraryMediaItem:
    return LibraryMediaItem(
        post_id='complete-post-id',
        created_at=_NOW,
        folder='pixel_forge/post',
        media_id=f'{kind.value}:piece',
        entry=MediaEntry(
            kind=kind,
            status=MediaStatus.downloaded,
            added_at=_NOW,
            position=0,
            path=f'{kind.value}/медиа.dat',
            size=512,
            removed_at=_NOW if kind == MediaKind.external_video else None,
        ),
        playback=None,
        thumbnail_path='pixel_forge/post/обложка.jpg',
    )


@pytest.fixture
def pages() -> MediaPages:
    items = [_item(kind) for kind in MediaKind]
    posts = {'complete-post-id': LibraryMediaPost('Шейдеры', None, _NOW, favorite=True)}
    return MediaPages(
        all=LibraryMediaPage(
            [item for item in items if item.entry.kind != MediaKind.file],
            posts,
            _COUNTS,
            missing=3,
        ),
        files=LibraryMediaPage([_item(MediaKind.file)], posts, _COUNTS, missing=2),
    )


def test_workload_checks_all_kinds_and_retained_removed_copies(
    pages: MediaPages,
) -> None:
    workload = validate_media_workload(
        pages.all, pages.files, expected_counts=_COUNTS, expected_removed=1
    )
    assert workload.counts == _COUNTS
    assert workload.all_items == 4
    assert workload.files_items == 1
    assert workload.downloaded == 5
    assert workload.removed == 1


def test_workload_rejects_trimming_to_a_smaller_sample(pages: MediaPages) -> None:
    with pytest.raises(ValueError, match='Expected media counts'):
        validate_media_workload(pages.all, pages.files)


def test_workload_rejects_incorrect_retained_removed_count(pages: MediaPages) -> None:
    with pytest.raises(ValueError, match='Expected 2 retained removed media; found 1'):
        validate_media_workload(
            pages.all, pages.files, expected_counts=_COUNTS, expected_removed=2
        )


def test_workload_rejects_files_aggregate_drift(pages: MediaPages) -> None:
    files = replace(pages.files, counts=replace(_COUNTS, videos=1))
    with pytest.raises(ValueError, match='aggregates differ'):
        validate_media_workload(
            pages.all, files, expected_counts=_COUNTS, expected_removed=1
        )


@pytest.mark.parametrize(
    'change', ['truncated', 'duplicate', 'extra-post', 'file', 'pending']
)
def test_query_validation_rejects_incomplete_or_wrong_results(
    pages: MediaPages, change: str
) -> None:
    page = pages.all
    match change:
        case 'truncated':
            page = replace(page, items=page.items[:-1])
        case 'duplicate':
            page = replace(page, items=page.items + page.items[:1])
        case 'extra-post':
            page = replace(
                page, posts={**page.posts, 'extra': next(iter(page.posts.values()))}
            )
        case 'file':
            page = replace(page, items=page.items[:-1] + pages.files.items)
        case 'pending':
            item = replace(
                page.items[0],
                entry=replace(page.items[0].entry, status=MediaStatus.pending),
            )
            page = replace(page, items=[item, *page.items[1:]])
        case _:
            pytest.fail(f'Unknown result corruption: {change}')
    with pytest.raises(ValueError, match=r'invalid|downloaded copy'):
        describe_media_query(MediaQuery('invalid'), page)


def test_serialization_preserves_complete_api_shape_and_utf8(pages: MediaPages) -> None:
    payload = serialize_response('pixel_forge', pages.all)
    response = MediaPage.model_validate_json(payload)
    assert len(response.items) == 4
    assert len(response.posts) == 1
    assert response.counts.all == 4
    assert response.counts.files == 1
    assert response.missing == 3
    assert response.posts['complete-post-id'].title == 'Шейдеры'
    assert response.posts['complete-post-id'].seen
    assert response.items[0].path.startswith('post/')
    assert response.items[0].thumb_path == 'post/обложка.jpg'
    assert 'Шейдеры'.encode() in payload
    assert gzip.decompress(compress_response(payload)) == payload
    size = response_size('pixel_forge', pages.all)
    assert size.json_bytes == len(payload)
    assert size.gzip_bytes == len(gzip.compress(payload, compresslevel=6, mtime=0))
    assert size.gzip_level == 6
    assert size.items == 4
    assert size.posts == 1


def test_json_report_retains_old_timing_fields_and_adds_workload_evidence(
    pages: MediaPages, tmp_path: Path
) -> None:
    workload = validate_media_workload(
        pages.all, pages.files, expected_counts=_COUNTS, expected_removed=1
    )
    query = describe_media_query(MediaQuery('complete_media_all'), pages.all)
    measurement = Measurement('complete_media_all', 0.1, (0.2, 0.1), 0.3)
    media = MediaBenchmark(
        workload, (query,), response_size('pixel_forge', pages.all), (measurement,)
    )
    result = ViewerBenchmark(
        PostWorkload('post-id', 5000, 2000, 1000), media, (measurement,)
    )
    report = json.loads(json.dumps(report_data(result, tmp_path, samples=2)))
    assert report['posts'] == 5000
    assert report['samples'] == 2
    assert report['media_workload']['downloaded'] == 5
    assert report['media_queries'][0]['query']['view'] == LibraryMediaView.all.value
    assert report['media_queries'][0]['items'] == 4
    assert report['post_workload']['seen_posts'] == 2000
    assert report['measurements'][0]['first_seconds'] == 0.1
    assert report['measurements'][0]['warm_median_seconds'] == pytest.approx(0.15)
    assert report['measurements'][0]['warm_minimum_seconds'] == 0.1
    assert report['measurements'][0]['warm_maximum_seconds'] == 0.2
    assert report['passed']
