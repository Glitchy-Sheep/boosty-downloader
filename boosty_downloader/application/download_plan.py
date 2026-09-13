"""
What a download run would fetch, computed the way the downloader itself decides.

The plan mirrors the real per-post flow: domain mapping (which drops unfinished
uploads and stream-only videos), the cache's missing-parts answer and the
content filters. Nothing here touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.filtering import (
    CHUNK_TO_FILTER,
    post_has_content_for,
)
from boosty_downloader.application.mappers.post_mapper import map_post_dto_to_domain
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from boosty_downloader.application.filtering import DownloadContentTypeFilter
    from boosty_downloader.domain.post import PostDataAllChunks
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
    from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
        BoostyOkVideoType,
    )
    from boosty_downloader.infrastructure.post_caching.post_cache import (
        SQLitePostCache,
    )


@dataclass(frozen=True, slots=True)
class DownloadPlan:
    """Where a download run would spend its time, per the current cache and filters."""

    new_posts: int
    # Cached before, but updated by the author or missing some parts.
    outdated_posts: int
    # Nothing missing: the run would skip them in seconds.
    complete_posts: int
    # Posts with missing parts but no content under the chosen filters.
    filtered_out_posts: int
    # Media pieces the run would fetch.
    media: MediaCounts
    # Bytes the API reports for those pieces (images, files, audio).
    known_bytes: int
    # Videos to fetch whose size the API does not tell.
    unknown_size_videos: int


def build_download_plan(
    posts: Iterable[PostDTO],
    *,
    post_cache: SQLitePostCache,
    filters: Sequence[DownloadContentTypeFilter],
    preferred_video_quality: BoostyOkVideoType,
) -> DownloadPlan:
    """Preview a download run. Locked posts are not planned: the run skips them."""
    new = outdated = complete = filtered_out = 0
    media = MediaCounts()
    known_bytes = 0
    unknown_size_videos = 0

    for post_dto in posts:
        if not post_dto.has_access:
            continue
        mapped = map_post_dto_to_domain(
            post_dto, preferred_video_quality=preferred_video_quality
        ).post
        missing = post_cache.get_post_missing_parts(
            post_uuid=mapped.uuid,
            updated_at=mapped.updated_at,
            required=list(filters),
        )
        if not missing:
            complete += 1
            continue
        if not post_has_content_for(mapped, missing):
            filtered_out += 1
            continue
        if post_cache.has_post(mapped.uuid):
            outdated += 1
        else:
            new += 1
        post_media, post_bytes, post_unknown = _media_to_fetch(
            mapped.post_data_chunks, missing
        )
        media += post_media
        known_bytes += post_bytes
        unknown_size_videos += post_unknown

    return DownloadPlan(
        new_posts=new,
        outdated_posts=outdated,
        complete_posts=complete,
        filtered_out_posts=filtered_out,
        media=media,
        known_bytes=known_bytes,
        unknown_size_videos=unknown_size_videos,
    )


def _media_to_fetch(
    chunks: Sequence[PostDataAllChunks],
    missing: Sequence[DownloadContentTypeFilter],
) -> tuple[MediaCounts, int, int]:
    """Media the run would fetch: counts, known bytes, unknown-size videos."""
    images = files = boosty_videos = external_videos = audio = 0
    known_bytes = 0
    unknown_size_videos = 0
    for chunk in chunks:
        if CHUNK_TO_FILTER.get(type(chunk)) not in missing:
            continue
        match chunk:
            case PostDataChunkImage():
                images += 1
                known_bytes += chunk.size or 0
            case PostDataChunkFile():
                files += 1
                known_bytes += chunk.size or 0
            case PostDataChunkAudio():
                audio += 1
                known_bytes += chunk.size or 0
            case PostDataChunkBoostyVideo():
                boosty_videos += 1
                unknown_size_videos += 1
            case PostDataChunkExternalVideo():
                external_videos += 1
                unknown_size_videos += 1
            case _:
                # Text and lists render into the page; they are not media.
                pass
    counts = MediaCounts(
        images=images,
        files=files,
        boosty_videos=boosty_videos,
        external_videos=external_videos,
        audio=audio,
    )
    return counts, known_bytes, unknown_size_videos
