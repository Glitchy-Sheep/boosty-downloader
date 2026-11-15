"""Keep remote access observations independent of downloaded post content."""

from __future__ import annotations

from asyncio import CancelledError
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
)
from boosty_downloader.application.filtering import has_excluded_tag
from boosty_downloader.application.mappers.image import to_domain_image_chunk
from boosty_downloader.application.mappers.post_metadata import map_post_metadata
from boosty_downloader.application.thumbnail_sync import ensure_teaser_thumbnail
from boosty_downloader.domain.stored_post import LockedPost
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadError,
)
from boosty_downloader.infrastructure.post_images import (
    download_locked_teaser,
    has_locked_teaser,
)

if TYPE_CHECKING:
    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO


async def observe_post_access(context: DownloadContext, post: PostDTO) -> None:
    """Save access metadata, retaining any teaser without changing downloaded content."""
    store = context.post_store
    if post.has_access:
        store.clear_locked_post(context.author_name, post.id)
        return
    previous = store.load_locked_post(context.author_name, post.id)
    observation = LockedPost(
        post=map_post_metadata(post, context.author_name),
        synced_at=datetime.now(timezone.utc),
        teaser_path=previous.teaser_path if previous is not None else None,
        teaser_thumbnail_path=previous.teaser_thumbnail_path
        if previous is not None
        else None,
    )
    store.save_locked_post(observation)
    if has_excluded_tag((tag.title for tag in post.tags or ()), context.excluded_tags):
        return
    path = await _ensure_teaser(context, post, observation.teaser_path)
    if path is not None:
        observation = replace(observation, teaser_path=path)
        store.save_locked_post(observation)
    thumbnail = await ensure_teaser_thumbnail(
        context, observation, url=_teaser_url(post)
    )
    if thumbnail is not None:
        store.save_locked_post(replace(observation, teaser_thumbnail_path=thumbnail))


async def _ensure_teaser(
    context: DownloadContext, post: PostDTO, previous_path: str | None
) -> str | None:
    try:
        if has_locked_teaser(context.library_root, context.author_name, previous_path):
            return None
        url = _teaser_url(post)
        if url is None:
            return None
        return await download_locked_teaser(
            session=context.downloader_session,
            library_root=context.library_root,
            author=context.author_name,
            post_id=post.id,
            url=url,
        )
    except (CancelledError, DownloadCancelledError) as error:
        raise ApplicationCancelledError(post.id) from error
    except (DownloadError, OSError, ValueError) as error:
        context.progress_reporter.warn(f'Could not download post teaser: {error}')
        return None


def _teaser_url(post: PostDTO) -> str | None:
    if not post.teaser or not post.teaser[0].url:
        return None
    return to_domain_image_chunk(post.teaser[0], post.signed_query).url
