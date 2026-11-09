"""Save missing video previews separately from the post's selected media transfers."""

from __future__ import annotations

from asyncio import CancelledError
from typing import TYPE_CHECKING

from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
)
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadError,
)
from boosty_downloader.infrastructure.post_images import download_post_preview

if TYPE_CHECKING:
    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.application.post_download_state import PostDownloadState
    from boosty_downloader.application.post_preparation import PreparedPost


async def ensure_post_previews(
    context: DownloadContext, state: PostDownloadState, prepared: PreparedPost
) -> None:
    """Fetch planned previews and persist each successful path before continuing."""
    for media_id in prepared.preview_download_ids:
        url = prepared.live.media[media_id].preview_url
        if not url:
            continue
        path = await _download_preview(context, state, media_id, url)
        if path is not None:
            state.complete_preview(media_id, path)


async def _download_preview(
    context: DownloadContext, state: PostDownloadState, media_id: str, url: str
) -> str | None:
    reservations = state.preview_path_reservations(media_id)
    try:
        return await download_post_preview(
            session=context.downloader_session,
            library_root=context.library_root,
            post_folder=state.folder,
            media_id=media_id,
            url=url,
            reserved_paths=reservations,
        )
    except (CancelledError, DownloadCancelledError) as error:
        raise ApplicationCancelledError(state.record.post.id) from error
    except (DownloadError, OSError, ValueError) as error:
        context.progress_reporter.warn(f'Could not download video preview: {error}')
        return None
