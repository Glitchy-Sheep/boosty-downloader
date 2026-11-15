"""Observe missing thumbnails without changing primary-media state or files."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.media_paths import find_recorded_file
from boosty_downloader.domain.post_data_chunks import PostDataChunkImage
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.infrastructure.post_thumbnails import has_thumbnail

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.mappers.live_post import LivePost
    from boosty_downloader.domain.disk_snapshot import DiskSnapshot
    from boosty_downloader.domain.stored_post import MediaEntry, StoredPost


def missing_thumbnail_ids(
    root: Path, live: LivePost, record: StoredPost | None, disk: DiskSnapshot
) -> tuple[str, ...]:
    """Select current saved images whose original exists and thumbnail needs work."""
    if record is None:
        return ()
    return tuple(
        media_id
        for media_id, media in live.media.items()
        if isinstance(media.download, PostDataChunkImage)
        and media.download.url
        and _has_original(record.media[media_id], disk)
        and _needs_thumbnail(root, record.post.author, record.media[media_id])
    )


def _has_original(entry: MediaEntry, disk: DiskSnapshot) -> bool:
    if (
        entry.kind is not MediaKind.image
        or entry.status is not MediaStatus.downloaded
        or entry.removed_at is not None
        or entry.path is None
    ):
        return False
    observed = find_recorded_file(entry.path, disk)
    return observed is not None and observed.size > 0


def _needs_thumbnail(root: Path, author: str, entry: MediaEntry) -> bool:
    try:
        return not has_thumbnail(root, author, entry.thumbnail_path)
    except (OSError, ValueError):
        # Optional path failures are reported by the download attempt.
        return True
