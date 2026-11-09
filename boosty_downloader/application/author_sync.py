"""Refresh the author's display metadata without changing post download results."""

from __future__ import annotations

from asyncio import CancelledError
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from boosty_downloader.application.mappers.blog_info import map_blog_info
from boosty_downloader.infrastructure.author_images import (
    AuthorImageKind,
    download_author_image,
)
from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIError
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadError,
)

if TYPE_CHECKING:
    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient


async def refresh_author(api: BoostyAPIClient, context: DownloadContext) -> None:
    """Refresh one real run's author; optional metadata failures only warn."""
    try:
        await _refresh_author(api, context)
    except (BoostyAPIError, OSError, ValueError) as error:
        context.progress_reporter.warn(f'Could not refresh author details: {error}')


async def _refresh_author(api: BoostyAPIClient, context: DownloadContext) -> None:
    previous = context.post_store.load_author(context.author_name)
    blog = await api.get_blog_info(context.author_name)
    author = map_blog_info(blog, context.author_name, datetime.now(timezone.utc))
    avatar_url = blog.owner.avatar_url if blog.owner is not None else None
    author.avatar_path = await _refresh_image(
        context,
        AuthorImageKind.avatar,
        avatar_url,
        previous.avatar_path if previous is not None else None,
    )
    author.cover_path = await _refresh_image(
        context,
        AuthorImageKind.cover,
        blog.cover_url,
        previous.cover_path if previous is not None else None,
    )
    context.post_store.save_author(author)


async def _refresh_image(
    context: DownloadContext,
    kind: AuthorImageKind,
    url: str | None,
    previous: str | None,
) -> str | None:
    if not url:
        return previous
    try:
        return await download_author_image(
            session=context.downloader_session,
            library_root=context.library_root,
            author=context.author_name,
            kind=kind,
            url=url,
        )
    except DownloadCancelledError as error:
        raise CancelledError from error
    except (DownloadError, OSError, ValueError) as error:
        context.progress_reporter.warn(
            f'Could not refresh author {kind.value}: {error}'
        )
        return previous
