"""Pure library-relative thumbnail projections and ordered post-cover candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.stored_post import MediaBlock, MediaKind, MediaStatus

if TYPE_CHECKING:
    from collections.abc import Iterator

    from boosty_downloader.domain.library import LibraryPost
    from boosty_downloader.domain.stored_post import MediaEntry


@dataclass(frozen=True, slots=True)
class CoverCandidate:
    """Library-relative image paths, with the original as this candidate's fallback."""

    thumbnail_path: str | None
    original_path: str | None = None


def media_thumbnail_path(author: str, folder: str, entry: MediaEntry) -> str | None:
    """Prefer an image's retained thumbnail; videos keep their saved preview."""
    if entry.kind is MediaKind.image:
        if entry.thumbnail_path is not None:
            return f'{author}/{entry.thumbnail_path}'
        if entry.status is MediaStatus.downloaded and entry.path is not None:
            return f'{folder}/{entry.path}'
    elif entry.kind in {MediaKind.boosty_video, MediaKind.external_video}:
        if entry.preview_path is not None:
            return f'{folder}/{entry.preview_path}'
    return None


def _current_media(content: LibraryPost) -> Iterator[MediaEntry]:
    if content.record is None:
        return
    seen: set[str] = set()
    for block in content.record.blocks:
        if not isinstance(block, MediaBlock) or block.media_id in seen:
            continue
        seen.add(block.media_id)
        entry = content.record.media[block.media_id]
        if entry.removed_at is None:
            yield entry


def _saved_candidates(content: LibraryPost) -> Iterator[CoverCandidate]:
    if content.folder is None:
        return
    author = content.overview.post.author
    for entry in _current_media(content):
        if entry.kind is not MediaKind.image:
            continue
        thumbnail = f'{author}/{entry.thumbnail_path}' if entry.thumbnail_path else None
        original = None
        if entry.status is MediaStatus.downloaded and entry.path is not None:
            original = f'{content.folder}/{entry.path}'
        yield CoverCandidate(thumbnail, original)
    for entry in _current_media(content):
        if entry.kind is MediaKind.boosty_video:
            yield CoverCandidate(media_thumbnail_path(author, content.folder, entry))
            return


def iter_cover_candidates(content: LibraryPost) -> Iterator[CoverCandidate]:
    """
    Try each current image, the first Boosty preview, then a locked teaser.

    A retained image thumbnail remains usable when its original has been deleted.
    Removed media and images absent from the current body never become covers.
    """
    yield from _saved_candidates(content)
    if content.overview.access is PostAccess.locked:
        author = content.overview.post.author
        thumbnail = content.teaser_thumbnail_path
        original = content.teaser_path
        yield CoverCandidate(
            f'{author}/{thumbnail}' if thumbnail is not None else None,
            f'{author}/{original}' if original is not None else None,
        )
