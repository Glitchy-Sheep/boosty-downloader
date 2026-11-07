"""Reconcile current post content with its retained local history."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from boosty_downloader.application._media_order import order_media_ids
from boosty_downloader.application.filtering import MEDIA_KIND_TO_FILTER
from boosty_downloader.application.media_paths import (
    find_media_file,
    find_recorded_file,
    get_preferred_media_path,
)
from boosty_downloader.domain.stored_post import (
    MediaBlock,
    MediaEntry,
    MediaStatus,
    PostSync,
    StoredPost,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping
    from collections.abc import Set as AbstractSet
    from datetime import datetime

    from boosty_downloader.application.mappers.live_post import LiveMedia, LivePost
    from boosty_downloader.application.media_paths import DiskSnapshot, FileMatch
    from boosty_downloader.domain.content_types import DownloadContentTypeFilter


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    """Owned post state and unique media IDs to fetch in current body order."""

    record: StoredPost | None
    download_ids: list[str]


def reconcile(  # noqa: PLR0913 - reconciliation combines saved/live state and run options
    stored: StoredPost | None,
    live: LivePost,
    disk: DiskSnapshot,
    filters: Collection[DownloadContentTypeFilter],
    now: datetime,
    *,
    restore_missing: bool = False,
    checked_unavailable_ids: AbstractSet[str] = frozenset(),
) -> ReconcileResult:
    """
    Reconcile a complete post and plan its downloads without I/O or input mutation.

    Empty filters select no downloads. The caller tracks checked unavailable IDs within this post and run; planning an attempt does not record its outcome.
    """
    record = prepare_record(stored, live, now)
    if not live.has_access or record is None:
        return ReconcileResult(record=record, download_ids=[])
    record = observe_recorded_files(record, disk)
    record = recover_media_files(record, live.media, disk)
    download_ids = _plan_downloads(
        record,
        live.media,
        filters,
        restore_missing=restore_missing,
        checked_unavailable_ids=checked_unavailable_ids,
    )
    return ReconcileResult(record=record, download_ids=download_ids)


def _plan_downloads(
    record: StoredPost,
    live_media: Mapping[str, LiveMedia],
    filters: Collection[DownloadContentTypeFilter],
    *,
    restore_missing: bool,
    checked_unavailable_ids: AbstractSet[str],
) -> list[str]:
    """Apply restore to the owned record and select ready current pieces."""
    download_ids: list[str] = []
    for media_id, entry in record.media.items():
        live = live_media.get(media_id)
        if live is None or entry.removed_at is not None:
            continue
        if MEDIA_KIND_TO_FILTER[live.kind] not in filters:
            continue
        if restore_missing and entry.status is MediaStatus.deleted:
            entry.status = MediaStatus.pending
        if live.download is None:
            continue
        if _is_download_due(media_id, entry.status, checked_unavailable_ids):
            download_ids.append(media_id)
    return download_ids


def _is_download_due(
    media_id: str, status: MediaStatus, checked_unavailable_ids: AbstractSet[str]
) -> bool:
    match status:
        case MediaStatus.pending | MediaStatus.failed:
            return True
        case MediaStatus.unavailable:
            return media_id not in checked_unavailable_ids
        case MediaStatus.downloaded | MediaStatus.deleted:
            return False


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
    return _downloaded_entry(entry, found)


def _downloaded_entry(entry: MediaEntry, found: FileMatch) -> MediaEntry:
    return replace(
        entry,
        status=MediaStatus.downloaded,
        path=found.path,
        size=found.size,
        error=None,
    )


def recover_media_files(
    record: StoredPost, live_media: Mapping[str, LiveMedia], disk: DiskSnapshot
) -> StoredPost:
    """
    Recover pending/failed/unavailable files in an independent record.

    The caller supplies an accessible post. Files must be nonempty and match the live size when known. Without live metadata, only the recorded path is considered.
    """
    recovered = deepcopy(record)
    reservations = {
        media_id: entry.path
        for media_id, entry in recovered.media.items()
        if entry.path is not None
    }
    order = sorted(
        recovered.media, key=lambda media_id: recovered.media[media_id].position
    )
    for media_id in order:
        entry = _recover_entry(
            media_id,
            recovered.media[media_id],
            live_media.get(media_id),
            disk,
            reservations,
        )
        recovered.media[media_id] = entry
        if entry.path is not None:
            reservations[media_id] = entry.path
    return recovered


def _recover_entry(
    media_id: str,
    entry: MediaEntry,
    live: LiveMedia | None,
    disk: DiskSnapshot,
    reservations: Mapping[str, str],
) -> MediaEntry:
    match entry.status:
        case MediaStatus.pending | MediaStatus.failed | MediaStatus.unavailable:
            found = _find_recoverable_file(media_id, entry, live, disk, reservations)
        case _:
            return entry
    if found is None:
        return entry
    return _downloaded_entry(entry, found)


def _find_recoverable_file(
    media_id: str,
    entry: MediaEntry,
    live: LiveMedia | None,
    disk: DiskSnapshot,
    reservations: Mapping[str, str],
) -> FileMatch | None:
    preferred = None
    expected_size = None
    if live is not None:
        preferred = get_preferred_media_path(media_id, live)
        expected_size = live.expected_size
    return find_media_file(
        media_id,
        disk,
        reservations,
        recorded_path=entry.path,
        preferred=preferred,
        expected_size=expected_size,
    )
