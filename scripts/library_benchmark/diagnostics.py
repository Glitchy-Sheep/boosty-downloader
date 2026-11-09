"""Changed-source timing with exact restoration of the owned synthetic records."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING, Final

from boosty_downloader.infrastructure.library._atomic_write import write_atomically
from boosty_downloader.infrastructure.library._post_json import (
    decode_post_record,
    encode_post_record,
)
from library_benchmark.fixture import iter_fixture_posts, prepare_fixture
from library_benchmark.measurements import Measurement

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from boosty_downloader.infrastructure.library.index import LibraryIndex
    from library_benchmark.fixture import FixtureDescription

_SAMPLE_STRIDE: Final = 100


@dataclass(frozen=True, slots=True)
class _SavedSource:
    path: Path
    data: bytes
    atime_ns: int
    mtime_ns: int


def measure_changed_sync(
    fixture: FixtureDescription, index: LibraryIndex, *, samples: int
) -> Measurement:
    """Measure synchronization of one percent of posts, excluding fixture edits."""
    if samples < 1:
        message = 'At least one changed-source timing sample is required'
        raise ValueError(message)
    prepare_fixture(fixture.root, fixture.config)
    sources = _sample_sources(fixture)
    elapsed: list[float] = []
    for _ in range(samples + 1):
        try:
            with _changed_sources(sources):
                started = perf_counter()
                counts = index.synchronize()
                elapsed.append(perf_counter() - started)
                if counts.posts_updated != len(sources):
                    message = 'Changed-source synchronization missed a fixture record'
                    raise RuntimeError(message)
        finally:
            index.synchronize()
    return Measurement('sync_one_percent_changed', elapsed[0], tuple(elapsed[1:]))


def _sample_sources(fixture: FixtureDescription) -> list[_SavedSource]:
    sources: list[_SavedSource] = []
    for number, item in enumerate(iter_fixture_posts(fixture.config)):
        if number % _SAMPLE_STRIDE:
            continue
        path = fixture.root / item.folder / 'post.json'
        info = path.stat()
        sources.append(
            _SavedSource(path, path.read_bytes(), info.st_atime_ns, info.st_mtime_ns)
        )
    return sources


@contextmanager
def _changed_sources(sources: list[_SavedSource]) -> Generator[None]:
    changed: list[_SavedSource] = []
    try:
        for source in sources:
            record = decode_post_record(source.data)
            record.post.likes += 1
            changed.append(source)
            write_atomically(source.path, encode_post_record(record))
        yield
    finally:
        for source in changed:
            write_atomically(source.path, source.data)
            os.utime(source.path, ns=(source.atime_ns, source.mtime_ns))
