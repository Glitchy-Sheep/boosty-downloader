"""Measure complete reader queries against the 5,000-post viewer sample author."""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from library_benchmark.measurements import Measurement, measure
from library_benchmark.viewer_media import MediaBenchmark, benchmark_media

from boosty_downloader.domain.library import PostFilters
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

_AUTHOR: Final = 'pixel_forge'
_POSTS: Final = 5000
_QUERY: Final = 'шейд'
_LIST_BUDGET_SECONDS: Final = 0.300
_DETAIL_BUDGET_SECONDS: Final = 0.150


@dataclass(frozen=True, slots=True)
class PostWorkload:
    """Validated post dimensions and the marks present during measurement."""

    detail_post_id: str
    posts: int
    seen_posts: int
    favorite_posts: int


@dataclass(frozen=True, slots=True)
class ViewerBenchmark:
    """Complete query timings and the full media-response payload size."""

    posts: PostWorkload
    media: MediaBenchmark
    measurements: tuple[Measurement, ...]


def benchmark(root: Path, *, samples: int) -> tuple[Measurement, ...]:
    """Retain the timing-only interface for existing benchmark callers."""
    return run_benchmark(root, samples=samples).measurements


def run_benchmark(root: Path, *, samples: int) -> ViewerBenchmark:
    """Validate the sample workload, then time fully materialized reader results."""
    if samples < 1:
        message = 'At least one warm timing sample is required'
        raise ValueError(message)
    if not root.is_dir():
        message = 'Generate the viewer sample with --posts 5912 before benchmarking'
        raise ValueError(message)
    reader = JsonLibraryReader(root)
    reader.prepare()
    posts = _validate_workload(reader)
    media = benchmark_media(
        reader, _AUTHOR, samples=samples, budget_seconds=_LIST_BUDGET_SECONDS
    )
    measurements = _measure_posts(reader, posts.detail_post_id, samples)
    return ViewerBenchmark(posts, media, measurements + media.measurements)


def _measure_posts(
    reader: JsonLibraryReader, post_id: str, samples: int
) -> tuple[Measurement, ...]:
    return (
        measure(
            'complete_post_list',
            lambda: reader.list_posts(_AUTHOR, PostFilters()),
            samples=samples,
            budget_seconds=_LIST_BUDGET_SECONDS,
        ),
        measure(
            'complete_search_list',
            lambda: reader.list_posts(_AUTHOR, PostFilters(text=_QUERY)),
            samples=samples,
            budget_seconds=_LIST_BUDGET_SECONDS,
        ),
        measure(
            'complete_post_detail',
            lambda: reader.post(_AUTHOR, post_id),
            samples=samples,
            budget_seconds=_DETAIL_BUDGET_SECONDS,
        ),
    )


def _validate_workload(reader: JsonLibraryReader) -> PostWorkload:
    posts = reader.list_posts(_AUTHOR, PostFilters())
    if posts.total != _POSTS or len(posts.rows) != _POSTS:
        message = f'Expected {_POSTS} posts for {_AUTHOR}; found {posts.total}'
        raise ValueError(message)
    results = reader.list_posts(_AUTHOR, PostFilters(text=_QUERY))
    if results.total < _POSTS - 2 or not all(row.match for row in results.rows):
        message = 'The search workload must include every saved body with hit runs'
        raise ValueError(message)
    post_id = posts.rows[0].overview.post.id
    detail = reader.post(_AUTHOR, post_id)
    if detail is None or detail.content.record is None:
        message = 'The detail workload requires a complete saved post body'
        raise ValueError(message)
    return PostWorkload(
        post_id,
        posts.total,
        sum(row.seen_at is not None for row in posts.rows),
        sum(row.favorite for row in posts.rows),
    )


def _measurement_report(measurement: Measurement) -> dict[str, object]:
    return {
        **asdict(measurement),
        'warm_median_seconds': measurement.median_seconds,
        'warm_minimum_seconds': measurement.minimum_seconds,
        'warm_maximum_seconds': measurement.maximum_seconds,
        'passed': measurement.passed,
    }


def report_data(
    result: ViewerBenchmark, root: Path, *, samples: int
) -> dict[str, object]:
    """Include workload evidence and explicit boundaries in the JSON timing report."""
    return {
        'root': str(root.resolve()),
        'author': _AUTHOR,
        'posts': result.posts.posts,
        'query': _QUERY,
        'samples': samples,
        'python': platform.python_version(),
        'sqlite': sqlite3.sqlite_version,
        'platform': platform.platform(),
        'cache': 'Preparation and validation precede timings; first is not a cold-cache sample.',
        'reader_boundary': 'Complete reader calls including all row and domain construction.',
        'response_boundary': 'Production mapping, UTF-8 model_dump_json and cumulative gzip; reader and HTTP transport excluded.',
        'post_workload': asdict(result.posts),
        'media_workload': asdict(result.media.workload),
        'media_queries': [asdict(query) for query in result.media.queries],
        'media_response': asdict(result.media.response),
        'measurements': [_measurement_report(item) for item in result.measurements],
        'passed': all(item.passed for item in result.measurements),
    }


def main() -> None:
    """Print environment and first/warm timings; fail if a warm median exceeds budget."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('.sample/viewer-queries'))
    parser.add_argument('--samples', type=int, default=5)
    options = parser.parse_args()
    if options.samples < 1:
        parser.error('--samples must be at least 1')
    try:
        result = run_benchmark(options.root, samples=options.samples)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Cannot benchmark viewer queries: {error}\n')
    report = report_data(result, options.root, samples=options.samples)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not all(item.passed for item in result.measurements):
        parser.exit(
            1, 'Viewer query budget exceeded; see first and warm samples above.\n'
        )


if __name__ == '__main__':
    main()
