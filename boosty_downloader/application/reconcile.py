"""Reconcile current post content with its retained local history."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import TYPE_CHECKING

from boosty_downloader.application._media_order import order_media_ids
from boosty_downloader.application.media_paths import find_recorded_file
from boosty_downloader.domain.stored_post import (
    MediaBlock,
    MediaEntry,
    MediaStatus,
    PostSync,
    StoredPost,
)

if TYPE_CHECKING:
    from datetime import datetime

    from boosty_downloader.application.mappers.live_post import LiveMedia, LivePost
    from boosty_downloader.application.media_paths import DiskSnapshot


def prepare_record(
    stored: StoredPost | None, live: LivePost, now: datetime
) -> StoredPost | None:
    """Refresh content and retained history without inspecting local files."""
    if not live.has_access:
        return deepcopy(stored)
    return StoredPost(
        post=deepcopy(live.post),
        sync=_prepare_sync(stored, now),
        blocks=deepcopy(live.blocks),
        media=_merge_media(stored, live, now),
    )


def _prepare_sync(stored: StoredPost | None, now: datetime) -> PostSync:
    if stored is None:
        return PostSync(first_downloaded_at=now, synced_at=now)
    return replace(deepcopy(stored.sync), synced_at=now)


def _merge_media(
    stored: StoredPost | None, live: LivePost, now: datetime
) -> dict[str, MediaEntry]:
    previous: dict[str, MediaEntry] = {}
    if stored is not None:
        previous = stored.media
    previous_order = sorted(previous, key=lambda media_id: previous[media_id].position)
    current_order = [
        block.media_id for block in live.blocks if isinstance(block, MediaBlock)
    ]
    merged: dict[str, MediaEntry] = {}
    for position, media_id in enumerate(order_media_ids(previous_order, current_order)):
        if media_id in live.media:
            merged[media_id] = _current_entry(
                previous.get(media_id), live.media[media_id], position, now
            )
        else:
            merged[media_id] = _removed_entry(previous[media_id], position, now)
    return merged


def _current_entry(
    previous: MediaEntry | None, live: LiveMedia, position: int, now: datetime
) -> MediaEntry:
    if previous is None:
        previous = MediaEntry(
            kind=live.kind,
            status=MediaStatus.pending,
            added_at=now,
            position=position,
        )
    return replace(
        deepcopy(previous),
        position=position,
        removed_at=None,
        title=live.title,
        filename=live.filename,
        artist=live.artist,
        duration=live.duration,
        width=live.width,
        height=live.height,
    )


def _removed_entry(previous: MediaEntry, position: int, now: datetime) -> MediaEntry:
    entry = deepcopy(previous)
    entry.position = position
    if entry.removed_at is None:
        entry.removed_at = now
    return entry


def observe_recorded_files(record: StoredPost, disk: DiskSnapshot) -> StoredPost:
    """
    Observe downloaded/deleted copies of an accessible post in an independent record.

    Missing copies keep their paths and last known sizes. Existing copies keep their actual sizes, including zero, even when the author removed the piece.
    """
    observed = deepcopy(record)
    observed.media = {
        media_id: _observe_saved_file(entry, disk)
        for media_id, entry in observed.media.items()
    }
    return observed


def _observe_saved_file(entry: MediaEntry, disk: DiskSnapshot) -> MediaEntry:
    match entry.status:
        case MediaStatus.downloaded | MediaStatus.deleted:
            return _recorded_file_state(entry, disk)
        case _:
            return entry


def _recorded_file_state(entry: MediaEntry, disk: DiskSnapshot) -> MediaEntry:
    found = None
    if entry.path is not None:
        found = find_recorded_file(entry.path, disk)
    if found is None:
        return replace(entry, status=MediaStatus.deleted)
    return replace(
        entry,
        status=MediaStatus.downloaded,
        path=found.path,
        size=found.size,
        error=None,
    )
