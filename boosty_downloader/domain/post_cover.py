"""Choose a post cover from its current body and observed local images."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.domain.stored_post import MediaBlock, MediaKind, MediaStatus

if TYPE_CHECKING:
    from collections.abc import Iterator

    from boosty_downloader.domain.disk_snapshot import DiskSnapshot
    from boosty_downloader.domain.stored_post import LockedPost, MediaEntry, StoredPost


def select_post_cover(record: StoredPost, disk: DiskSnapshot) -> str | None:
    """Return a post-relative cover path, preferring images over the first video."""
    for entry in _current_media(record):
        if entry.kind is MediaKind.image and entry.status is MediaStatus.downloaded:
            path = _available_image(entry.path, disk)
            if path is not None:
                return path
    for entry in _current_media(record):
        if entry.kind is MediaKind.boosty_video:
            return _available_image(entry.preview_path, disk)
    return None


def select_locked_cover(post: LockedPost, disk: DiskSnapshot) -> str | None:
    """Return an author-relative teaser path observed in the author's snapshot."""
    return _available_image(post.teaser_path, disk)


def _current_media(record: StoredPost) -> Iterator[MediaEntry]:
    for block in record.blocks:
        if isinstance(block, MediaBlock):
            entry = record.media[block.media_id]
            if entry.removed_at is None:
                yield entry


def _available_image(path: str | None, disk: DiskSnapshot) -> str | None:
    if path is None:
        return None
    observed = path if path in disk.files else disk.aliases.get(path)
    if observed is None or disk.files.get(observed, 0) <= 0:
        return None
    return observed
