"""Observe only candidate cover paths, never all media in a library."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING

from boosty_downloader.domain.disk_snapshot import DiskSnapshot
from boosty_downloader.domain.post_cover import select_post_cover
from boosty_downloader.domain.stored_post import MediaBlock, MediaKind, MediaStatus
from boosty_downloader.infrastructure.library._media_paths import (
    is_link,
    resolve_post_folder,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from boosty_downloader.domain.library import LibraryPost
    from boosty_downloader.domain.stored_post import StoredPost


def find_cover_path(root: Path, post: LibraryPost) -> str | None:
    """Return a usable library-relative cover, falling back to a locked teaser."""
    if post.record is not None and post.folder is not None:
        folder = resolve_post_folder(root, post.folder)
        files = {
            path: size
            for path in _cover_candidates(post.record)
            if (size := _image_size(folder, path)) is not None
        }
        selected = select_post_cover(post.record, DiskSnapshot(files))
        if selected is not None:
            return (PurePosixPath(post.folder) / selected).as_posix()
    if (
        post.teaser_path is not None
        and _image_size(root / post.overview.post.author, post.teaser_path) is not None
    ):
        return (PurePosixPath(post.overview.post.author) / post.teaser_path).as_posix()
    return None


def _cover_candidates(record: StoredPost) -> Iterator[str]:
    first_video_seen = False
    for block in record.blocks:
        if not isinstance(block, MediaBlock):
            continue
        entry = record.media[block.media_id]
        if entry.removed_at is not None:
            continue
        if (
            entry.kind is MediaKind.image
            and entry.status is MediaStatus.downloaded
            and entry.path is not None
        ):
            yield entry.path
        if entry.kind is MediaKind.boosty_video and not first_video_seen:
            first_video_seen = True
            if entry.preview_path is not None:
                yield entry.preview_path


def _image_size(folder: Path, relative: str) -> int | None:
    current = folder
    parts = PurePosixPath(relative).parts
    try:
        for part in parts[:-1]:
            current /= part
            info = current.lstat()
            if is_link(info) or not S_ISDIR(info.st_mode):
                return None
        info = (current / parts[-1]).lstat()
    except (FileNotFoundError, NotADirectoryError):
        return None
    if is_link(info) or not S_ISREG(info.st_mode) or info.st_size <= 0:
        return None
    return info.st_size
