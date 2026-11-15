"""Preview exact media work from the same saved records as real downloads."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.filtering import has_excluded_tag
from boosty_downloader.application.planned_post_pages import PlannedPostPages
from boosty_downloader.application.post_locations import ReservedPostLocator
from boosty_downloader.domain.stored_post import MediaKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from boosty_downloader.application.post_preparation import (
        PostPreparer,
        PreparedPost,
    )
    from boosty_downloader.domain.content_types import DownloadContentTypeFilter
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    """Record changes and selected media work, with no persistent writes."""

    new_posts: int
    updated_posts: int
    unchanged_posts: int
    excluded_posts: int
    media: MediaCounts
    known_bytes: int
    unknown_size_videos: int


@dataclass(frozen=True, slots=True)
class PlannedMedia:
    """Selected pieces and their current API size estimates."""

    counts: MediaCounts = field(default_factory=MediaCounts)
    known_bytes: int = 0
    unknown_size_videos: int = 0

    def __add__(self, other: PlannedMedia) -> PlannedMedia:
        """Combine counts and estimates from separate posts."""
        return PlannedMedia(
            self.counts + other.counts,
            self.known_bytes + other.known_bytes,
            self.unknown_size_videos + other.unknown_size_videos,
        )


def first_post_observations(posts: Iterable[PostDTO]) -> Iterator[PostDTO]:
    """Keep one author's first snapshot of each full post ID in listing order."""
    seen_post_ids: set[str] = set()
    for post in posts:
        if post.id in seen_post_ids:
            continue
        seen_post_ids.add(post.id)
        yield post


def build_download_plan(
    posts: Iterable[PostDTO],
    *,
    preparer: PostPreparer,
    filters: Sequence[DownloadContentTypeFilter],
    excluded_tags: Sequence[str] = (),
    now: datetime | None = None,
) -> DownloadPlan:
    """Use each full ID's first observation; exclusions precede any record lookup."""
    observed_at = now or datetime.now(timezone.utc)
    locations = ReservedPostLocator(preparer.store)
    pages = PlannedPostPages(preparer.library_root, preparer.store)
    preparer = replace(preparer, store=locations)
    new = updated = unchanged = excluded = 0
    media = PlannedMedia()
    for post in first_post_observations(posts):
        if has_excluded_tag((tag.title for tag in post.tags or ()), excluded_tags):
            excluded += 1
            continue
        if not post.has_access:
            continue
        prepared = preparer.prepare(post, filters, observed_at)
        locations.reserve(prepared.live.post, prepared.folder)
        pages.record(prepared)
        if prepared.is_new:
            new += 1
        elif prepared.needs_update:
            updated += 1
        else:
            unchanged += 1
        media += _planned_media(prepared)
    refreshed = pages.count_updated_sources()
    return DownloadPlan(
        new_posts=new,
        updated_posts=updated + refreshed,
        unchanged_posts=unchanged - refreshed,
        excluded_posts=excluded,
        media=media.counts,
        known_bytes=media.known_bytes,
        unknown_size_videos=media.unknown_size_videos,
    )


def _planned_media(prepared: PreparedPost) -> PlannedMedia:
    counts: Counter[MediaKind] = Counter()
    known_bytes = unknown_videos = 0
    for media_id in prepared.reconciliation.download_ids:
        media = prepared.live.media[media_id]
        counts[media.kind] += 1
        if media.expected_size is not None:
            known_bytes += media.expected_size
        elif media.kind in {MediaKind.boosty_video, MediaKind.external_video}:
            unknown_videos += 1
    return PlannedMedia(
        counts=MediaCounts(
            images=counts[MediaKind.image],
            files=counts[MediaKind.file],
            boosty_videos=counts[MediaKind.boosty_video],
            external_videos=counts[MediaKind.external_video],
            audio=counts[MediaKind.audio],
        ),
        known_bytes=known_bytes,
        unknown_size_videos=unknown_videos,
    )
