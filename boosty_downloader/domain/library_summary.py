"""Browsing values derived from one fresh canonical post snapshot."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from boosty_downloader.domain.content_counters import RemoteCounter
from boosty_downloader.domain.library import MediaCounts, PostRow
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import datetime

    from boosty_downloader.domain.library import LibraryPost, LibraryPostDetails
    from boosty_downloader.domain.stored_post import MediaEntry


def remote_media_counts(counts: Mapping[str, int]) -> MediaCounts:
    """Summarize remote counters when no saved media inventory exists."""
    return MediaCounts(
        images=counts.get(RemoteCounter.image.value, 0),
        videos=counts.get(RemoteCounter.platform_video.value, 0)
        + counts.get(RemoteCounter.external_video.value, 0),
        files=counts.get(RemoteCounter.file.value, 0),
        audio=counts.get(RemoteCounter.audio.value, 0),
    )


def saved_media_counts(counts: Mapping[str, int]) -> MediaCounts:
    """Combine saved media categories into the viewer's four counts."""
    return MediaCounts(
        images=counts.get(MediaKind.image.value, 0),
        videos=counts.get(MediaKind.boosty_video.value, 0)
        + counts.get(MediaKind.external_video.value, 0),
        files=counts.get(MediaKind.file.value, 0),
        audio=counts.get(MediaKind.audio.value, 0),
    )


def summarize_post(detail: LibraryPostDetails) -> PostRow:
    """Keep metadata, marks and inventory from the same detail read."""
    content, marks = detail.content, detail.marks
    entries = list(content.record.media.values()) if content.record else []
    current = [entry for entry in entries if entry.removed_at is None]
    return PostRow(
        overview=content.overview,
        cover_path=detail.cover_path,
        counts=_detail_counts(content, current),
        missing_media=sum(
            entry.status is not MediaStatus.downloaded for entry in current
        ),
        seen_at=marks.seen_at,
        favorite=marks.favorite,
        pieces_added_at=latest_media_added_at(entries),
    )


def _detail_counts(content: LibraryPost, current: Sequence[MediaEntry]) -> MediaCounts:
    if content.record is None:
        return remote_media_counts(content.overview.post.content_counters)
    return saved_media_counts(Counter(entry.kind.value for entry in current))


def latest_media_added_at(entries: Iterable[MediaEntry]) -> datetime | None:
    """Find the newest current piece or retained downloaded copy."""
    return max(
        (
            entry.added_at
            for entry in entries
            if entry.removed_at is None or entry.status is MediaStatus.downloaded
        ),
        default=None,
    )
