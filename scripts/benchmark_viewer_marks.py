"""Measure 1,000 durable mark changes in an isolated production sample library."""

from __future__ import annotations

import argparse
import json
import platform
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Final

from library_sample.asset_models import AssetBackend
from library_sample.generator import prepare_sample
from library_sample.models import AuthorName, SampleConfig

from boosty_downloader.domain.library import PostFilters
from boosty_downloader.domain.library_mutations import BulkMarkProgress
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

_AUTHOR: Final = AuthorName.devlog.value
_ELIGIBLE_POSTS: Final = 1000
_SAMPLE_POSTS: Final = 1198


@dataclass(frozen=True, slots=True)
class MarkMeasurement:
    """One complete canonical-write and index-refresh operation."""

    name: str
    elapsed_seconds: float
    changed: int
    progress_updates: int
    first_completed_seconds: float | None
    final_progress: BulkMarkProgress


@dataclass
class _ProgressRecorder:
    started: float
    updates: int = 0
    first_completed_seconds: float | None = None
    latest: BulkMarkProgress | None = None

    def record(self, progress: BulkMarkProgress) -> None:
        """Retain bounded timing evidence while checking every reported count."""
        if not 0 <= progress.changed <= progress.completed <= progress.total:
            message = 'Bulk progress has inconsistent counts'
            raise RuntimeError(message)
        if self.latest is not None and progress.completed < self.latest.completed:
            message = 'Bulk progress moved backwards'
            raise RuntimeError(message)
        self.updates += 1
        self.latest = progress
        if progress.completed and self.first_completed_seconds is None:
            self.first_completed_seconds = perf_counter() - self.started


def _measure(
    reader: JsonLibraryReader, name: str, *, seen: bool, expected: int
) -> MarkMeasurement:
    started = perf_counter()
    recorder = _ProgressRecorder(started)
    changed = reader.set_seen_many(
        _AUTHOR, PostFilters(), seen=seen, progress=recorder.record
    )
    elapsed = perf_counter() - started
    final = recorder.latest
    if (
        changed is None
        or final is None
        or changed != expected
        or final != BulkMarkProgress(_ELIGIBLE_POSTS, _ELIGIBLE_POSTS, expected)
    ):
        message = f'{name}: expected {expected} changes and complete progress'
        raise RuntimeError(message)
    return MarkMeasurement(
        name,
        elapsed,
        changed,
        recorder.updates,
        recorder.first_completed_seconds,
        final,
    )


def _check_workload(reader: JsonLibraryReader) -> None:
    author = reader.author(_AUTHOR)
    if author is None or author.counts.posts - author.counts.locked != _ELIGIBLE_POSTS:
        message = 'The sample must contain exactly 1,000 eligible posts'
        raise RuntimeError(message)


def benchmark(temporary_parent: Path | None = None) -> tuple[MarkMeasurement, ...]:
    """Create and remove only a fresh temporary sample; never modify a user library."""
    with TemporaryDirectory(
        prefix='boosty-mark-benchmark-', dir=temporary_parent
    ) as tmp:
        root = Path(tmp) / 'library'
        prepare_sample(
            root,
            SampleConfig(seed=7, posts=_SAMPLE_POSTS),
            backend=AssetBackend.fallback,
        )
        reader = JsonLibraryReader(root)
        reader.prepare()
        _check_workload(reader)
        reader.set_seen_many(_AUTHOR, PostFilters(), seen=False)
        return (
            _measure(reader, 'mark_seen', seen=True, expected=_ELIGIBLE_POSTS),
            _measure(reader, 'repeat_seen', seen=True, expected=0),
            _measure(reader, 'mark_unseen', seen=False, expected=_ELIGIBLE_POSTS),
        )


def main() -> None:
    """Print complete measured runs; sample generation is outside their timings."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--temporary-parent',
        type=Path,
        help='Existing directory on the disk to measure',
    )
    options = parser.parse_args()
    measurements = benchmark(options.temporary_parent)
    print(
        json.dumps(
            {
                'python': platform.python_version(),
                'platform': platform.platform(),
                'sqlite': sqlite3.sqlite_version,
                'sample_posts': _SAMPLE_POSTS,
                'eligible_posts': _ELIGIBLE_POSTS,
                'measurements': [asdict(item) for item in measurements],
            },
            indent=2,
        )
    )


if __name__ == '__main__':
    main()
