"""Require verified WAL fixes and FTS5 before accessing a primary library."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from dataclasses import dataclass
from functools import cache
from typing import Final

from boosty_downloader.infrastructure.library._db_errors import (
    UnsupportedLibraryDatabaseError,
)


@dataclass(frozen=True, slots=True, order=True)
class _SQLiteVersion:
    major: int
    minor: int
    patch: int


_FIXED_MAINLINE: Final = _SQLiteVersion(3, 51, 3)
_FIXED_BACKPORTS: Final = (_SQLiteVersion(3, 50, 7), _SQLiteVersion(3, 44, 6))


def require_supported_sqlite() -> None:
    """Check the loaded runtime without opening library files or creating sidecars."""
    version = _SQLiteVersion(*sqlite3.sqlite_version_info)
    if not _has_verified_wal_fix(version):
        reason = 'the WAL-reset fix is unverified for this SQLite version'
        raise _runtime_error(reason)
    _require_fts5()


def _has_verified_wal_fix(version: _SQLiteVersion) -> bool:
    if version >= _FIXED_MAINLINE:
        return True
    return any(
        version.major == fixed.major
        and version.minor == fixed.minor
        and version.patch >= fixed.patch
        for fixed in _FIXED_BACKPORTS
    )


@cache
def _require_fts5() -> None:
    """Probe FTS5 once per loaded runtime; failed probes are never cached."""
    try:
        with closing(sqlite3.connect(':memory:')) as connection:
            connection.execute(
                'CREATE VIRTUAL TABLE runtime_probe USING fts5(value)'
            ).close()
    except sqlite3.Error as error:
        reason = 'the in-memory FTS5 probe failed'
        raise _runtime_error(reason) from error


def _runtime_error(reason: str) -> UnsupportedLibraryDatabaseError:
    return UnsupportedLibraryDatabaseError(
        f'Unsupported primary-library SQLite runtime: {reason}. '
        f'Python executable: {sys.executable}; SQLite: {sqlite3.sqlite_version}. '
        'Update or recreate the Python environment containing this executable with '
        'a Python build linked to SQLite 3.51.3 or newer, 3.50.7+ within 3.50, '
        'or 3.44.6+ within 3.44, with FTS5 enabled. '
        'Older version reports require verified vendor backport provenance.'
    )
