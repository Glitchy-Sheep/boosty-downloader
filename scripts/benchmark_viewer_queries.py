"""Measure complete reader queries against the 5,000-post viewer sample author."""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Final

from library_benchmark.measurements import Measurement, measure

from boosty_downloader.domain.library import PostFilters
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

_AUTHOR: Final = 'pixel_forge'
_POSTS: Final = 5000
_QUERY: Final = 'шейд'
_LIST_BUDGET_SECONDS: Final = 0.300
_DETAIL_BUDGET_SECONDS: Final = 0.150


def benchmark(root: Path, *, samples: int) -> tuple[Measurement, ...]:
    """Validate the sample workload, then time fully materialized reader results."""
    if not root.is_dir():
        message = 'Generate the viewer sample with --posts 5912 before benchmarking'
        raise ValueError(message)
    reader = JsonLibraryReader(root)
    reader.prepare()
    post_id = _validate_workload(reader)
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


def _validate_workload(reader: JsonLibraryReader) -> str:
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
    return post_id


def _measurement_report(measurement: Measurement) -> dict[str, object]:
    return {
        **asdict(measurement),
        'warm_median_seconds': measurement.median_seconds,
        'warm_minimum_seconds': measurement.minimum_seconds,
        'warm_maximum_seconds': measurement.maximum_seconds,
        'passed': measurement.passed,
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
        measurements = benchmark(options.root, samples=options.samples)
    except (OSError, ValueError) as error:
        parser.exit(1, f'Cannot benchmark viewer queries: {error}\n')
    report = {
        'root': str(options.root.resolve()),
        'author': _AUTHOR,
        'posts': _POSTS,
        'query': _QUERY,
        'python': platform.python_version(),
        'sqlite': sqlite3.sqlite_version,
        'platform': platform.platform(),
        'measurements': [_measurement_report(item) for item in measurements],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    if not all(item.passed for item in measurements):
        parser.exit(
            1, 'Viewer query budget exceeded; see first and warm samples above.\n'
        )


if __name__ == '__main__':
    main()
