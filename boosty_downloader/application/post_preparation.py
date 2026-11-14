"""Read saved state and prepare the same media work for downloads and previews."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from boosty_downloader.application.mappers.live_post import map_post_dto_to_live
from boosty_downloader.application.media_paths import (
    find_recorded_file,
    get_media_alias_queries,
    get_preferred_media_path,
)
from boosty_downloader.application.reconcile import reconcile
from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.stored_post import MediaEntry, MediaKind, MediaStatus
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.media_snapshot import (
    confirm_media_aliases,
    read_media_snapshot,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from collections.abc import Set as AbstractSet
    from datetime import datetime
    from pathlib import Path

    from boosty_downloader.application.mappers.live_post import LivePost
    from boosty_downloader.application.media_paths import MediaPathHint
    from boosty_downloader.application.ports import PostLocator
    from boosty_downloader.application.reconcile import ReconcileResult
    from boosty_downloader.domain.content_types import DownloadContentTypeFilter
    from boosty_downloader.domain.disk_snapshot import DiskSnapshot
    from boosty_downloader.domain.stored_post import StoredPost
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
    from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
        BoostyOkVideoType,
    )


@dataclass(frozen=True, slots=True)
class PreparedPost:
    """An accessible post's observed state and owned reconciliation result."""

    live: LivePost
    stored: StoredPost | None
    folder: str
    disk: DiskSnapshot
    reconciliation: ReconcileResult
    page_exists: bool
    record_changed: bool
    preview_download_ids: tuple[str, ...] = ()

    @property
    def is_new(self) -> bool:
        """Whether a new record is needed, even when its folder already exists."""
        return self.stored is None

    @property
    def page_needs_update(self) -> bool:
        """Whether the observed page is missing or uses another template version."""
        return (
            not self.page_exists
            or self.stored is None
            or self.stored.sync.page_template != PAGE_TEMPLATE_VERSION
        )

    @property
    def needs_update(self) -> bool:
        """Whether selected media, saved content or page state needs work."""
        return (
            bool(self.reconciliation.download_ids)
            or bool(self.preview_download_ids)
            or self.record_changed
            or self.page_needs_update
        )


@dataclass(frozen=True, slots=True)
class PostPreparer:
    """
    Read-only preparation for selected accessible posts of one author.

    Callers apply tag exclusions before preparation. Construction and preparation do not save records, render pages or change access observations.
    """

    library_root: Path
    store: PostLocator
    author: str
    preferred_video_quality: BoostyOkVideoType
    restore_missing: bool = False

    def prepare(
        self,
        post_dto: PostDTO,
        filters: Collection[DownloadContentTypeFilter],
        now: datetime,
        *,
        checked_unavailable_ids: AbstractSet[str] = frozenset(),
    ) -> PreparedPost:
        """Read current state; reject locked posts and propagate storage errors."""
        if not post_dto.has_access:
            message = 'Cannot prepare downloads for a locked post'
            raise ValueError(message)
        live = map_post_dto_to_live(post_dto, self.author, self.preferred_video_quality)
        located = self._locate_post(live)
        disk = _observe_files(self.library_root, located, live)
        result = reconcile(
            located.record,
            live,
            disk,
            filters,
            now,
            restore_missing=self.restore_missing,
            checked_unavailable_ids=checked_unavailable_ids,
        )
        return _prepared_post(live, located, disk, result)

    def _locate_post(self, live: LivePost) -> LocatedPost:
        located = self.store.find_post(self.author, live.post.id)
        if located is not None:
            return located
        return LocatedPost(folder=self.store.choose_post_folder(live.post))


def _prepared_post(
    live: LivePost, located: LocatedPost, disk: DiskSnapshot, result: ReconcileResult
) -> PreparedPost:
    return PreparedPost(
        live=live,
        stored=located.record,
        folder=located.folder,
        disk=disk,
        reconciliation=result,
        page_exists=find_recorded_file('post.html', disk) is not None,
        record_changed=_has_record_changes(located.record, result.record),
        preview_download_ids=_preview_download_ids(live, result.record, disk),
    )


def _observe_files(
    library_root: Path, located: LocatedPost, live: LivePost
) -> DiskSnapshot:
    disk = read_media_snapshot(library_root, located.folder)
    queries = get_media_alias_queries(_recovery_hints(located.record, live), disk)
    queries.add('post.html')
    if located.record is not None:
        queries.update(
            path
            for entry in located.record.media.values()
            for path in (entry.path, entry.preview_path)
            if path is not None
        )
    return confirm_media_aliases(library_root, located.folder, disk, queries)


def _recovery_hints(
    stored: StoredPost | None, live: LivePost
) -> dict[str, MediaPathHint]:
    """Known downloaded/deleted pieces are observed only at their recorded paths."""
    previous = stored.media if stored is not None else {}
    hints: dict[str, MediaPathHint] = {}
    for media_id, media in live.media.items():
        match previous.get(media_id):
            case MediaEntry(status=MediaStatus.downloaded | MediaStatus.deleted):
                continue
            case _:
                pass
        hint = get_preferred_media_path(media_id, media)
        if hint is not None:
            hints[media_id] = hint
    return hints


def _has_record_changes(stored: StoredPost | None, record: StoredPost | None) -> bool:
    if stored is None or record is None:
        return stored != record
    comparable = replace(
        record, sync=replace(record.sync, synced_at=stored.sync.synced_at)
    )
    return comparable != stored


def _preview_download_ids(
    live: LivePost, record: StoredPost | None, disk: DiskSnapshot
) -> tuple[str, ...]:
    if record is None:
        return ()
    return tuple(
        media_id
        for media_id, media in live.media.items()
        if media.kind is MediaKind.boosty_video
        and media.preview_url
        and _needs_preview(record.media[media_id], disk)
    )


def _needs_preview(entry: MediaEntry, disk: DiskSnapshot) -> bool:
    if entry.preview_path is None:
        return True
    found = find_recorded_file(entry.preview_path, disk)
    return found is None or found.size == 0
