"""Counters of one download run: filled as posts finish, shown at the end."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from boosty_downloader.application.blog_overview import MediaCounts


@dataclass(slots=True)
class RunStatistics:
    """What one download run did so far."""

    started_at: float = field(default_factory=time.monotonic)
    posts_downloaded: int = 0
    # Skipped: cached and up to date.
    posts_cached: int = 0
    # Skipped: nothing under the chosen filters.
    posts_without_content: int = 0
    posts_failed: int = 0
    # Skipped: this account cannot open them.
    posts_locked: int = 0
    media: MediaCounts = field(default_factory=MediaCounts)
    downloaded_bytes: int = 0

    def add_media(self, media: MediaCounts, downloaded_bytes: int) -> None:
        """Count one finished media download."""
        self.media += media
        self.downloaded_bytes += downloaded_bytes

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at
