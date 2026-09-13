"""The cache files of one creator on disk, handled without opening the database."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.post_caching.post_cache import SQLitePostCache

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class SQLiteCacheStorage:
    """Existence and removal of the cache database in a creator's cache directory."""

    destination: Path

    @property
    def _db_file(self) -> Path:
        return self.destination / SQLitePostCache.DEFAULT_CACHE_FILENAME

    def exists(self) -> bool:
        return self._db_file.exists()

    def remove(self) -> None:
        """Delete the database; drop the directory too when nothing else is in it."""
        self._db_file.unlink(missing_ok=True)
        with suppress(OSError):
            # Keep the folder when it still holds downloaded posts.
            self.destination.rmdir()
