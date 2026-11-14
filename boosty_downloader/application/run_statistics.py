"""Counters of one download run: filled as posts finish, shown at the end."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.domain.library import PostIdentity


@dataclass(slots=True)
class RunStatistics:
    """What one download run did so far."""

    started_at: float = field(default_factory=time.monotonic)
    posts_downloaded: int = 0
    # No content or local state change is needed under the selected filters.
    posts_cached: int = 0
    # Skipped: nothing under the chosen filters.
    posts_without_content: int = 0
    posts_failed: int = 0
    # Skipped: this account cannot open them.
    posts_locked: int = 0
    media: MediaCounts = field(default_factory=MediaCounts)
    downloaded_bytes: int = 0
    media_deleted: int = 0
    _pending_posts: set[PostIdentity] = field(
        default_factory=set[PostIdentity], init=False, repr=False
    )

    @property
    def posts_pending(self) -> int:
        """Posts whose final page comparison has not completed."""
        return len(self._pending_posts)

    def record_pending_post(self, identity: PostIdentity) -> None:
        """Wait for the final page check before classifying an otherwise cached post."""
        self._pending_posts.add(identity)

    def finish_pending_post(self, identity: PostIdentity, *, written: bool) -> None:
        """Count each completed page check once, preserving partial run results."""
        if identity not in self._pending_posts:
            return
        self._pending_posts.remove(identity)
        if written:
            self.posts_downloaded += 1
        else:
            self.posts_cached += 1

    def add_media(self, media: MediaCounts, downloaded_bytes: int) -> None:
        """Count one finished media download."""
        self.media += media
        self.downloaded_bytes += downloaded_bytes

    def elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at
