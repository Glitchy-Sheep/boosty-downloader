"""Shared streaming and temporary ownership for library images."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from aiohttp import ClientError

from boosty_downloader.infrastructure.file_downloader import (
    DownloadError,
    copy_download_response,
    download_errors,
)
from boosty_downloader.infrastructure.media_workspace import (
    cleanup_owned_workspaces,
    temporary_owned_workspace,
)
from boosty_downloader.infrastructure.media_writer import open_media_writer

if TYPE_CHECKING:
    from collections.abc import Generator
    from contextlib import ExitStack
    from pathlib import Path

    from aiohttp import ClientResponse


def enter_image_workspace(stack: ExitStack, parent: Path, *, owner_id: str) -> Path:
    """
    Create an owned image workspace beside a validated parent.

    The caller excludes concurrent transfers of this owner and closes its writers before stack exit.
    """
    cleanup_owned_workspaces(parent, owner_id=owner_id)
    return stack.enter_context(temporary_owned_workspace(parent, owner_id=owner_id))


async def write_image_response(
    response: ClientResponse, source: Path, filename: str
) -> None:
    """Stream bounded response chunks and close the file before returning."""
    async with open_media_writer(source) as writer:
        await copy_download_response(response, writer.write, filename=filename)


def require_image_bytes(source: Path, url: str) -> None:
    """Reject an empty completed response before publishing an image."""
    if source.stat().st_size == 0:
        message = 'Image response is empty'
        raise DownloadError(message, file=None, resource_url=url)


@contextmanager
def image_errors(url: str, *, label: str) -> Generator[None, None, None]:
    """Translate image transfer failures without exposing signed URLs in messages."""
    try:
        with download_errors(url):
            yield
    except ValueError as error:
        message = f'Invalid {label.lower()} destination or URL'
        raise DownloadError(message, file=None, resource_url=url) from error
    except ClientError as error:
        message = f'{label} request failed'
        raise DownloadError(message, file=None, resource_url=url) from error
