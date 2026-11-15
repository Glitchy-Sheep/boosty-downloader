"""Save optional image thumbnails without changing primary-media outcomes."""

from __future__ import annotations

from asyncio import CancelledError
from typing import TYPE_CHECKING

from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
)
from boosty_downloader.domain.post_data_chunks import PostDataChunkImage
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadError,
)
from boosty_downloader.infrastructure.post_images import has_locked_teaser
from boosty_downloader.infrastructure.post_thumbnails import (
    download_post_thumbnail,
    download_teaser_thumbnail,
    has_thumbnail,
)

if TYPE_CHECKING:
    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.application.mappers.live_post import LiveMedia
    from boosty_downloader.application.post_download_state import PostDownloadState
    from boosty_downloader.application.post_preparation import PreparedPost
    from boosty_downloader.domain.stored_post import LockedPost


async def ensure_saved_thumbnails(
    context: DownloadContext, state: PostDownloadState, prepared: PreparedPost
) -> None:
    """Backfill the current saved images selected by read-only preparation."""
    for media_id in prepared.thumbnail_download_ids:
        await ensure_image_thumbnail(
            context, state, media_id, prepared.live.media[media_id]
        )


async def ensure_image_thumbnail(
    context: DownloadContext, state: PostDownloadState, media_id: str, media: LiveMedia
) -> None:
    """Persist each thumbnail after its original has been saved successfully."""
    chunk = media.download
    entry = state.record.media[media_id]
    if (
        not isinstance(chunk, PostDataChunkImage)
        or entry.status is not MediaStatus.downloaded
        or entry.removed_at is not None
    ):
        return
    path = await _image_thumbnail(context, state, media_id, chunk.url)
    if path is not None:
        state.complete_thumbnail(media_id, path)


async def _image_thumbnail(
    context: DownloadContext, state: PostDownloadState, media_id: str, url: str
) -> str | None:
    post = state.record.post
    try:
        if has_thumbnail(
            context.library_root,
            post.author,
            state.record.media[media_id].thumbnail_path,
        ):
            return None
        async with context.thumbnail_requests:
            return await download_post_thumbnail(
                session=context.downloader_session,
                library_root=context.library_root,
                author=post.author,
                post_id=post.id,
                media_id=media_id,
                url=url,
            )
    except (CancelledError, DownloadCancelledError) as error:
        raise ApplicationCancelledError(post.id) from error
    except (DownloadError, OSError, ValueError) as error:
        _warn_once(context, error)
        return None


async def ensure_teaser_thumbnail(
    context: DownloadContext, post: LockedPost, *, url: str | None
) -> str | None:
    """Fill a missing thumbnail only when the locked post's original teaser exists."""
    if url is None:
        return None
    author = post.post.author
    try:
        if not has_locked_teaser(context.library_root, author, post.teaser_path):
            return None
        if has_thumbnail(context.library_root, author, post.teaser_thumbnail_path):
            return None
        async with context.thumbnail_requests:
            return await download_teaser_thumbnail(
                session=context.downloader_session,
                library_root=context.library_root,
                author=author,
                post_id=post.post.id,
                url=url,
            )
    except (CancelledError, DownloadCancelledError) as error:
        raise ApplicationCancelledError(post.post.id) from error
    except (DownloadError, OSError, ValueError) as error:
        _warn_once(context, error)
        return None


def _warn_once(context: DownloadContext, error: Exception) -> None:
    if context.thumbnail_warning_reported:
        return
    context.thumbnail_warning_reported = True
    context.progress_reporter.warn(f'Could not download thumbnail: {error}')
