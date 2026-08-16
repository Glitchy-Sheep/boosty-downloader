"""Characterization of the SQLite post cache (pre-refactoring safety net).

Pins the cache's contract before the layering stages move it around:
what counts as missing for fresh, partial and outdated posts, and how
the cache behaves when its database file is broken.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import DatabaseError

from boosty_downloader.src.application.filtering import DownloadContentTypeFilter
from boosty_downloader.src.infrastructure.loggers.base import RichLogger
from boosty_downloader.src.infrastructure.post_caching.post_cache import (
    SQLitePostCache,
)

if TYPE_CHECKING:
    from pathlib import Path

ALL_PARTS = list(DownloadContentTypeFilter)
UPDATED_AT = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
UPDATED_LATER = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def _open_cache(destination: Path) -> SQLitePostCache:
    return SQLitePostCache(destination=destination, logger=RichLogger('cache-test'))


def test_unknown_post_needs_every_required_part(tmp_path: Path):
    """A cache miss must not look like "already downloaded" - the post would be lost."""
    with _open_cache(tmp_path) as cache:
        assert cache.get_post_missing_parts('p1', UPDATED_AT, ALL_PARTS) == ALL_PARTS


def test_fully_cached_post_needs_nothing(tmp_path: Path):
    """The point of the cache: a second run must not re-download anything."""
    with _open_cache(tmp_path) as cache:
        cache.cache_post('p1', UPDATED_AT, ALL_PARTS)
        assert cache.get_post_missing_parts('p1', UPDATED_AT, ALL_PARTS) == []


def test_partial_download_reports_only_the_gap(tmp_path: Path):
    """A filtered run must not re-fetch the parts an earlier run already saved."""
    files = DownloadContentTypeFilter.files
    post_content = DownloadContentTypeFilter.post_content
    with _open_cache(tmp_path) as cache:
        cache.cache_post('p1', UPDATED_AT, [files])
        missing = cache.get_post_missing_parts('p1', UPDATED_AT, [files, post_content])
    assert missing == [post_content]


def test_author_update_invalidates_every_part(tmp_path: Path):
    """An edited post must be re-downloaded in full even if it was fully cached."""
    with _open_cache(tmp_path) as cache:
        cache.cache_post('p1', UPDATED_AT, ALL_PARTS)
        assert cache.get_post_missing_parts('p1', UPDATED_LATER, ALL_PARTS) == ALL_PARTS


def test_second_run_extends_the_first(tmp_path: Path):
    """Marking audio as downloaded must not erase the files flag from an earlier run."""
    files = DownloadContentTypeFilter.files
    audio = DownloadContentTypeFilter.audio
    with _open_cache(tmp_path) as cache:
        cache.cache_post('p1', UPDATED_AT, [files])
        cache.cache_post('p1', UPDATED_AT, [audio])
        assert cache.get_post_missing_parts('p1', UPDATED_AT, [files, audio]) == []


def test_cache_survives_reopen(tmp_path: Path):
    """State must live in the file, not in the session: every run is a new process."""
    with _open_cache(tmp_path) as cache:
        cache.cache_post('p1', UPDATED_AT, ALL_PARTS)
    with _open_cache(tmp_path) as cache:
        assert cache.get_post_missing_parts('p1', UPDATED_AT, ALL_PARTS) == []


def test_clean_cache_forgets_everything(tmp_path: Path):
    """clean-cache promises a fresh start - a surviving row would block re-download."""
    with _open_cache(tmp_path) as cache:
        cache.cache_post('p1', UPDATED_AT, ALL_PARTS)
        cache.remove_cache_completely()
        assert cache.get_post_missing_parts('p1', UPDATED_AT, ALL_PARTS) == ALL_PARTS
        # The reinitialized database must stay writable.
        cache.cache_post('p2', UPDATED_AT, ALL_PARTS)
        assert cache.get_post_missing_parts('p2', UPDATED_AT, ALL_PARTS) == []


def test_outdated_schema_triggers_clean_reinit(tmp_path: Path):
    """A hand-edited or ancient database must reset, not crash the run."""
    db_file = tmp_path / SQLitePostCache.DEFAULT_CACHE_FILENAME
    connection = sqlite3.connect(db_file)
    connection.execute('CREATE TABLE post_cache (post_uuid TEXT PRIMARY KEY)')
    connection.commit()
    connection.close()

    with _open_cache(tmp_path) as cache:
        assert cache.get_post_missing_parts('p1', UPDATED_AT, ALL_PARTS) == ALL_PARTS
        cache.cache_post('p1', UPDATED_AT, ALL_PARTS)
        assert cache.get_post_missing_parts('p1', UPDATED_AT, ALL_PARTS) == []


@pytest.mark.xfail(
    reason='migrations run before the corruption check, so a non-SQLite cache '
    'file crashes startup instead of reinitializing (audit 15.3)',
    raises=DatabaseError,
    strict=True,
)
def test_corrupted_file_triggers_clean_reinit(tmp_path: Path):
    """Desired contract: any broken database resets instead of killing the run."""
    (tmp_path / SQLitePostCache.DEFAULT_CACHE_FILENAME).write_bytes(b'not a database')
    with _open_cache(tmp_path) as cache:
        assert cache.get_post_missing_parts('p1', UPDATED_AT, ALL_PARTS) == ALL_PARTS
