"""Storage-neutral media queries and independent browsing snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from boosty_downloader.domain.library import PostOrder

if TYPE_CHECKING:
    from datetime import datetime

    from boosty_downloader.domain.library import MediaCounts
    from boosty_downloader.domain.library_marks import PlaybackPosition
    from boosty_downloader.domain.stored_post import MediaEntry


class LibraryMediaView(str, Enum):
    """Media categories; All excludes files and Video includes both sources."""

    all = 'all'
    image = 'image'
    video = 'video'
    audio = 'audio'
    file = 'file'


@dataclass(frozen=True, slots=True)
class MediaFilters:
    """Viewing marks and post date order for one author's media."""

    unseen_only: bool = False
    favorites_only: bool = False
    order: PostOrder = PostOrder.newest


@dataclass(frozen=True, slots=True)
class MediaIdentity:
    """A piece identified by its full post ID and post-local media key."""

    post_id: str
    media_id: str


@dataclass(frozen=True, slots=True)
class LibraryMediaItem:
    """A detached piece; folder and thumbnail are library-relative, entry paths post-relative."""

    post_id: str
    created_at: datetime
    folder: str
    media_id: str
    entry: MediaEntry
    playback: PlaybackPosition | None
    thumbnail_path: str | None = None


@dataclass(frozen=True, slots=True)
class LibraryMediaPost:
    """Shared post metadata with a library-relative cover path."""

    title: str
    cover_path: str | None
    seen_at: datetime | None
    favorite: bool


@dataclass(frozen=True, slots=True)
class LibraryMediaPage:
    """Selected pieces, their posts, counts across views and selected missing pieces."""

    items: list[LibraryMediaItem]
    posts: dict[str, LibraryMediaPost]
    counts: MediaCounts
    missing: int
