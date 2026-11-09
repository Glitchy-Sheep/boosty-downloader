"""Storage-neutral identities, snapshots and progress for user mark changes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

    from boosty_downloader.domain.library import LibraryAuthor, PostRow
    from boosty_downloader.domain.library_marks import PlaybackPosition
    from boosty_downloader.domain.stored_post import MediaEntry


@dataclass(frozen=True, slots=True)
class MediaIdentity:
    """A piece identified by its full post ID and post-local media key."""

    post_id: str
    media_id: str


@dataclass(frozen=True, slots=True)
class LibraryMediaItem:
    """One independent media snapshot with a library-relative post folder."""

    post_id: str
    created_at: datetime
    folder: str
    media_id: str
    entry: MediaEntry
    playback: PlaybackPosition | None


@dataclass(frozen=True, slots=True)
class PostMarkResult:
    """Fresh post state and author totals after a successful mark update."""

    post: PostRow
    author: LibraryAuthor


@dataclass(frozen=True, slots=True)
class BulkMarkProgress:
    """Selected posts, completed updates and actual canonical mark changes."""

    total: int
    completed: int
    changed: int
