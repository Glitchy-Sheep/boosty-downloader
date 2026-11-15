"""The benchmark validates its results and restores its exclusively owned data."""

from __future__ import annotations

import json
from dataclasses import replace
from typing import TYPE_CHECKING

import benchmark_library
import pytest
from library_benchmark.diagnostics import measure_changed_sync
from library_benchmark.fixture import FixtureConfig, prepare_fixture
from library_benchmark.measurements import Measurement, measure
from library_benchmark.queries import (
    QueryValidationError,
    build_queries,
    execute_query,
    verify_query,
)
from library_benchmark.runner import BenchmarkReport, report_data, run_benchmark

from boosty_downloader.infrastructure.library.index import LibraryIndex

if TYPE_CHECKING:
    from pathlib import Path

    from library_benchmark.fixture import FixtureDescription

    from boosty_downloader.infrastructure.library.index import IndexSyncCounts


@pytest.fixture
def config() -> FixtureConfig:
    return FixtureConfig(authors=2, posts_per_author=20)


def _sources(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob('*')
        if path.is_file() and not path.name.startswith('index.db')
    }


def test_queries_validate_all_rows_against_the_generated_library(
    tmp_path: Path, config: FixtureConfig
):
    fixture = prepare_fixture(tmp_path / 'library', config)
    index = LibraryIndex(fixture.root)
    index.rebuild()
    queries = build_queries(config)
    with index.connect() as connection:
        for query in queries:
            actual = execute_query(connection, query)
            verify_query(query, actual)
            assert actual.rows
    assert {query.name for query in queries} == {
        'sql_posts_by_date',
        'sql_video_unseen_tag',
        'sql_months',
        'sql_author_counts',
        'sql_fts_prefix',
        'sql_storage_all',
        'sql_storage_author',
    }


def test_verifier_rejects_incorrect_results(tmp_path: Path, config: FixtureConfig):
    fixture = prepare_fixture(tmp_path / 'library', config)
    index = LibraryIndex(fixture.root)
    index.rebuild()
    query = build_queries(config)[0]
    with index.connect() as connection:
        actual = execute_query(connection, query)
    with pytest.raises(QueryValidationError, match='expected 20 rows, got 19'):
        verify_query(query, replace(actual, rows=actual.rows[:-1]))


def test_measurement_reports_first_and_warm_samples_and_strict_budget(
    monkeypatch: pytest.MonkeyPatch,
):
    times = iter([0.0, 4.0, 10.0, 11.0, 20.0, 23.0, 30.0, 32.0])
    monkeypatch.setattr(
        'library_benchmark.measurements.perf_counter', lambda: next(times)
    )
    calls: list[str] = []
    result = measure(
        'sample', lambda: calls.append('called'), samples=3, budget_seconds=2.0
    )
    assert len(calls) == 4
    assert result.first_seconds == 4.0
    assert result.warm_seconds == (1.0, 3.0, 2.0)
    assert result.median_seconds == 2.0
    assert result.minimum_seconds == 1.0
    assert result.maximum_seconds == 3.0
    assert not result.passed
    assert replace(result, budget_seconds=None).passed


def test_measurement_rejects_no_warm_samples():
    with pytest.raises(ValueError, match='At least one'):
        measure('empty', lambda: None, samples=0)


def test_complete_smoke_run_restores_source_bytes_and_mtimes(
    tmp_path: Path,
    config: FixtureConfig,
):
    fixture = prepare_fixture(tmp_path / 'library', config)
    before = _sources(fixture.root)
    report = run_benchmark(
        fixture, samples=1, rebuild_samples=1, progress=lambda _: None
    )
    assert _sources(fixture.root) == before
    assert prepare_fixture(fixture.root, config) == fixture
    assert not report.acceptance_workload
    assert len(report.measurements) == 11
    data = report_data(report)
    assert data['fixture'] == {
        'authors': 2,
        'posts': 40,
        'media': 200,
        'marks': fixture.marks,
        'locked': fixture.locked,
        'cover_files': fixture.cover_files,
        'source_bytes': fixture.source_bytes,
        'seed': config.seed,
    }
    json.dumps(data)


def test_changed_sync_restores_sources_after_an_index_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    fixture = prepare_fixture(
        tmp_path / 'library', FixtureConfig(authors=1, posts_per_author=120)
    )
    index = LibraryIndex(fixture.root)
    index.rebuild()
    before = _sources(fixture.root)
    original = index.synchronize
    calls = 0

    def fail_once() -> IndexSyncCounts:
        nonlocal calls
        calls += 1
        if calls == 1:
            message = 'injected index failure'
            raise RuntimeError(message)
        return original()

    monkeypatch.setattr(index, 'synchronize', fail_once)
    with pytest.raises(RuntimeError, match='injected index failure'):
        measure_changed_sync(fixture, index, samples=1)
    assert _sources(fixture.root) == before
    assert prepare_fixture(fixture.root, fixture.config) == fixture
    assert original().posts_updated == 0


def test_generate_only_creates_fixture_without_an_index(tmp_path: Path):
    root = tmp_path / 'library'
    result = benchmark_library.main(
        [str(root), '--authors', '1', '--posts-per-author', '2', '--generate-only']
    )
    assert result == 0
    assert not (root / '.boosty-downloader' / 'index.db').exists()


def test_cli_missed_budget_returns_failure_and_json_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    def fake_run(fixture: FixtureDescription, **_kwargs: object) -> BenchmarkReport:
        return BenchmarkReport(
            fixture, '3.12', '3', 'test', (Measurement('rebuild', 20.0, (20.0,), 10.0),)
        )

    monkeypatch.setattr(benchmark_library, 'run_benchmark', fake_run)
    report_path = tmp_path / 'report.json'
    result = benchmark_library.main(
        [
            str(tmp_path / 'library'),
            '--authors',
            '1',
            '--posts-per-author',
            '2',
            '--json',
            str(report_path),
        ]
    )
    assert result == 1
    report = json.loads(report_path.read_text())
    assert report['passed'] is False
    assert report['acceptance_workload'] is False
    assert report['measurements'][0]['median_seconds'] == 20.0


def test_cli_refuses_report_inside_fixture_before_creating_files(tmp_path: Path):
    root = tmp_path / 'library'
    with pytest.raises(SystemExit) as error:
        benchmark_library.main([str(root), '--json', str(root / 'post.json')])
    assert error.value.code == 2
    assert not root.exists()
