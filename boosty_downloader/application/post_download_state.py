"""Persist one post's reservations and media outcomes on its owning event loop."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from boosty_downloader.application.media_paths import reserve_media_path
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.infrastructure.media_output_paths import (
    resolve_media_destination,
)
from boosty_downloader.infrastructure.media_transfer import MediaTarget

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import PostStore
    from boosty_downloader.application.post_preparation import PreparedPost
    from boosty_downloader.domain.stored_post import MediaEntry, StoredPost
    from boosty_downloader.infrastructure.media_publication import PublishedFile


@dataclass(slots=True)
class PostRunProgress:
    """Media outcomes counted or checked during this post's entire retry run."""

    counted_media_ids: set[str] = field(default_factory=set[str])
    checked_unavailable_ids: set[str] = field(default_factory=set[str])
    deleted_media_count: int = 0


class PostDownloadState:
    """
    Own the saved record of one prepared attempt and its synchronous updates.

    Callers await transfers outside these methods and read the record without mutating it. Each save completes before another transfer can reserve or report a result on the event loop.
    """

    def __init__(
        self,
        library_root: Path,
        store: PostStore,
        prepared: PreparedPost,
        progress: PostRunProgress,
    ) -> None:
        if prepared.reconciliation.record is None:
            message = 'A download attempt requires an accessible post record'
            raise ValueError(message)
        self._root = library_root
        self._store = store
        self._prepared = prepared
        self._progress = progress
        self._record = deepcopy(prepared.reconciliation.record)
        self._disk = prepared.disk
        self._download_ids = frozenset(prepared.reconciliation.download_ids)

    @property
    def record(self) -> StoredPost:
        """The current saved-state candidate, read without caller mutation."""
        return self._record

    @property
    def folder(self) -> str:
        """The stable post folder relative to the library root."""
        return self._prepared.folder

    def save_initial(self) -> None:
        """Save reconciliation and keep an unfinished page rebuild discoverable."""
        record = self._record
        if self._prepared.needs_update:
            record = _invalidate_page(record)
        self._save(record)

    def reserve(self, media_id: str, filename: str) -> MediaTarget:
        """Save a concrete pending destination before any media bytes are written."""
        entry = self._download_entry(media_id)
        preferred = _preferred_path(entry, filename)
        reservations = {
            owner: media.path
            for owner, media in self._record.media.items()
            if media.path is not None
        }
        path = reserve_media_path(preferred, media_id, self._disk, reservations)
        resolve_media_destination(self._root, self.folder, path)
        self._save_entry(
            media_id,
            replace(
                entry, path=path, size=None, status=MediaStatus.pending, error=None
            ),
        )
        return MediaTarget(self._root, self.folder, path, media_id)

    def complete(self, media_id: str, result: PublishedFile) -> bool:
        """Save the published path and bytes; count each piece only once per run."""
        entry = self._record.media[media_id]
        path = self._published_path(entry, result)
        self._save_entry(
            media_id,
            replace(entry, status=MediaStatus.downloaded, size=result.size, error=None),
        )
        self._disk = replace(self._disk, files={**self._disk.files, path: result.size})
        first_completion = media_id not in self._progress.counted_media_ids
        self._progress.counted_media_ids.add(media_id)
        return first_completion

    def fail(self, media_id: str, error: str, *, unavailable: bool = False) -> None:
        """Persist failure before any asynchronous logging or next retry."""
        entry = self._record.media[media_id]
        status = _failure_status(unavailable=unavailable)
        self._save_entry(media_id, replace(entry, status=status, error=error))
        if unavailable:
            self._progress.checked_unavailable_ids.add(media_id)

    def mark_rendered(self, template_version: int) -> None:
        """Save the template marker after the complete page was rendered."""
        sync = replace(self._record.sync, page_template=template_version)
        self._save(replace(self._record, sync=sync))

    def _download_entry(self, media_id: str) -> MediaEntry:
        if media_id not in self._download_ids:
            message = 'The media piece was not selected for this attempt'
            raise ValueError(message)
        entry = self._record.media[media_id]
        if entry.status is MediaStatus.downloaded:
            message = 'A completed media piece cannot reserve another output'
            raise ValueError(message)
        return entry

    def _published_path(self, entry: MediaEntry, result: PublishedFile) -> str:
        if entry.path is None:
            message = 'A published media piece requires a saved reservation'
            raise ValueError(message)
        expected = resolve_media_destination(self._root, self.folder, entry.path)
        if result.path != expected:
            message = 'Published media does not match its saved reservation'
            raise ValueError(message)
        if type(result.size) is not int or result.size < 0:
            message = 'Published media size must be a nonnegative byte count'
            raise ValueError(message)
        return entry.path

    def _save_entry(self, media_id: str, entry: MediaEntry) -> None:
        media = {**self._record.media, media_id: entry}
        self._save(_invalidate_page(replace(self._record, media=media)))

    def _save(self, record: StoredPost) -> None:
        self._store.save_post(self.folder, record)
        self._record = record


def _invalidate_page(record: StoredPost) -> StoredPost:
    return replace(record, sync=replace(record.sync, page_template=None))


def _preferred_path(entry: MediaEntry, filename: str) -> str:
    if not filename or '/' in filename or '\\' in filename:
        message = 'A transport must reserve a filename without directory components'
        raise ValueError(message)
    if entry.path is not None and _same_suffix(entry.path, filename):
        return entry.path
    return f'{_media_folder(entry.kind)}/{filename}'


def _same_suffix(path: str, filename: str) -> bool:
    return (
        PurePosixPath(path).suffix.casefold()
        == PurePosixPath(filename).suffix.casefold()
    )


def _failure_status(*, unavailable: bool) -> MediaStatus:
    if unavailable:
        return MediaStatus.unavailable
    return MediaStatus.failed


def _media_folder(kind: MediaKind) -> str:
    match kind:
        case MediaKind.image:
            return 'images'
        case MediaKind.file:
            return 'files'
        case MediaKind.audio:
            return 'audio'
        case MediaKind.boosty_video:
            return 'boosty_videos'
        case MediaKind.external_video:
            return 'external_videos'
