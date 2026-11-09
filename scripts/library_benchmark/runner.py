"""End-to-end index measurements and explicit SQL timing boundaries."""

from __future__ import annotations

import platform
import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

from boosty_downloader.domain.library import PostFilters
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader
from library_benchmark.diagnostics import measure_changed_sync
from library_benchmark.fixture import FixtureConfig, FixtureDescription, author_name
from library_benchmark.measurements import (
    OPEN_BUDGET_SECONDS,
    QUERY_BUDGET_SECONDS,
    REBUILD_BUDGET_SECONDS,
    Measurement,
    measure,
)
from library_benchmark.queries import build_queries, execute_query, verify_query

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy import Connection

    from library_benchmark.queries import QueryCase


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Environment, workload and every measured first/warm operation."""

    fixture: FixtureDescription
    python: str
    sqlite: str
    platform: str
    measurements: tuple[Measurement, ...]

    @property
    def passed(self) -> bool:
        return all(measurement.passed for measurement in self.measurements)

    @property
    def acceptance_workload(self) -> bool:
        default = FixtureConfig()
        return (
            self.fixture.config.authors == default.authors
            and self.fixture.config.posts_per_author == default.posts_per_author
        )


def run_benchmark(
    fixture: FixtureDescription,
    *,
    samples: int = 5,
    rebuild_samples: int = 3,
    progress: Callable[[str], None] = print,
) -> BenchmarkReport:
    """Exercise production rebuild/open paths and then validate measured SQL."""
    index = LibraryIndex(fixture.root)
    measurements = [_measure_rebuild(index, rebuild_samples, progress)]
    progress('Measuring unchanged open, including integrity and source checks')
    measurements.append(
        measure(
            'open_unchanged',
            lambda: _unchanged_open(index),
            samples=samples,
            budget_seconds=OPEN_BUDGET_SECONDS,
        )
    )
    queries = build_queries(fixture.config)
    with index.connect() as connection:
        measurements.extend(
            _measure_query(connection, query, samples, progress) for query in queries
        )
    reader = JsonLibraryReader(fixture.root)
    progress('Measuring complete reader output separately from SQL budgets')
    measurements.append(
        measure(
            'reader_posts_by_date',
            lambda: reader.list_posts(author_name(0), PostFilters()),
            samples=samples,
        )
    )
    progress('Measuring one-percent source changes, then restoring the fixture')
    measurements.append(measure_changed_sync(fixture, index, samples=samples))
    return BenchmarkReport(
        fixture,
        platform.python_version(),
        sqlite3.sqlite_version,
        platform.platform(),
        tuple(measurements),
    )


def _measure_rebuild(
    index: LibraryIndex, samples: int, progress: Callable[[str], None]
) -> Measurement:
    progress('Measuring complete production index rebuild')
    result = measure(
        'rebuild', index.rebuild, samples=samples, budget_seconds=REBUILD_BUDGET_SECONDS
    )
    progress(f'Rebuild warm median: {result.median_seconds:.3f} s')
    return result


def _unchanged_open(index: LibraryIndex) -> None:
    counts = index.synchronize()
    if counts.rebuilt or any(
        (
            counts.authors_updated,
            counts.posts_updated,
            counts.posts_removed,
            counts.authors_removed,
        )
    ):
        message = 'Unchanged open unexpectedly modified the index'
        raise RuntimeError(message)


def _measure_query(
    connection: Connection,
    query: QueryCase,
    samples: int,
    progress: Callable[[str], None],
) -> Measurement:
    verify_query(query, execute_query(connection, query))
    progress(f'Measuring {query.name}')
    return measure(
        query.name,
        lambda: execute_query(connection, query),
        samples=samples,
        budget_seconds=QUERY_BUDGET_SECONDS,
    )


def report_data(report: BenchmarkReport) -> dict[str, object]:
    """Produce a portable JSON report, including computed budget verdicts."""
    fixture = report.fixture
    return {
        'library_root': str(fixture.root),
        'python': report.python,
        'sqlite': report.sqlite,
        'platform': report.platform,
        'cache': 'Warm filesystem cache; no cold-cache or network-storage guarantee',
        'sql_boundary': 'Bound SQL execution and all DB-API row fetching; no ORM/DTO construction',
        'acceptance_workload': report.acceptance_workload,
        'passed': report.passed,
        'fixture': {
            'authors': fixture.config.authors,
            'posts': fixture.posts,
            'media': fixture.media,
            'marks': fixture.marks,
            'locked': fixture.locked,
            'cover_files': fixture.cover_files,
            'source_bytes': fixture.source_bytes,
            'seed': fixture.config.seed,
        },
        'measurements': [_measurement_data(item) for item in report.measurements],
    }


def _measurement_data(item: Measurement) -> dict[str, object]:
    return {
        'name': item.name,
        'first_seconds': item.first_seconds,
        'warm_seconds': item.warm_seconds,
        'median_seconds': item.median_seconds,
        'minimum_seconds': item.minimum_seconds,
        'maximum_seconds': item.maximum_seconds,
        'budget_seconds': item.budget_seconds,
        'passed': item.passed,
    }


def print_report(report: BenchmarkReport) -> None:
    """Show timings in milliseconds and distinguish small smoke workloads."""
    fixture = report.fixture
    print(
        f'Library: {fixture.config.authors} authors, {fixture.posts} posts, {fixture.media} media, {fixture.source_bytes / 1_000_000:.1f} MB source JSON'
    )
    print(f'Python {report.python}; SQLite {report.sqlite}; {report.platform}')
    print(
        'Warm filesystem cache. SQL includes execution/fetch, excludes ORM/domain construction.'
    )
    if not report.acceptance_workload:
        print(
            'Smoke workload only: these results do not establish the 20,000-post budgets.'
        )
    print(
        f'{"Operation":<30} {"First ms":>11} {"Median ms":>11} {"Min ms":>11} {"Max ms":>11} {"Budget ms":>11}  Result'
    )
    for item in report.measurements:
        budget = (
            '-' if item.budget_seconds is None else f'{item.budget_seconds * 1000:.1f}'
        )
        verdict = _verdict(item)
        print(
            f'{item.name:<30} {item.first_seconds * 1000:>11.3f} {item.median_seconds * 1000:>11.3f} {item.minimum_seconds * 1000:>11.3f} {item.maximum_seconds * 1000:>11.3f} {budget:>11}  {verdict}'
        )


def _verdict(item: Measurement) -> str:
    if item.budget_seconds is None:
        return 'diagnostic'
    return 'PASS' if item.passed else 'FAIL'
