"""Module to download files with reporting process mechanisms"""

from __future__ import annotations

import http
import mimetypes
from typing import TYPE_CHECKING, Callable

import aiofiles
from pydantic import BaseModel

from boosty_downloader.src.download_manager.utils.path_sanitizer import sanitize_string

if TYPE_CHECKING:
    from pathlib import Path

    import aiohttp


class DownloadingStatus(BaseModel):
    """
    Model for status of the download.

    Can be used in status update callbacks.
    """

    total_bytes: int | None
    downloaded_bytes: int
    name: str


class DownloadFileConfig(BaseModel):
    """General configuration for the file download"""

    session: aiohttp.ClientSession
    url: str

    filename: str
    destination: Path
    on_status_update: Callable[[DownloadingStatus], None] = lambda _: None


class DownloadFailureError(Exception):
    """Exception raised when the download failed for any reason"""


async def download_file(
    dl_config: DownloadFileConfig,
) -> None:
    """Download files and report the downloading process via callback"""
    async with dl_config.session.get(dl_config.url) as response:
        if response.status != http.HTTPStatus.OK:
            raise DownloadFailureError

        filename = sanitize_string(dl_config.filename)
        file_path = dl_config.destination / filename

        content_type = response.content_type
        if content_type:
            ext = mimetypes.guess_extension(content_type)
            if ext is not None:
                file_path = file_path.with_suffix(ext)

        total_downloaded = 0

        async with aiofiles.open(file_path, mode='wb') as file:
            total_size = response.content_length

            async for chunk in response.content.iter_chunked(8192):
                total_downloaded += len(chunk)
                dl_config.on_status_update(
                    DownloadingStatus(
                        name=filename,
                        total_bytes=total_size,
                        downloaded_bytes=total_downloaded,
                    ),
                )
                await file.write(chunk)
