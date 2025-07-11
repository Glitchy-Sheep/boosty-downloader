"""Module to download files with reporting process mechanisms"""

from __future__ import annotations

import http
import mimetypes
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiofiles

from boosty_downloader.src.download_manager.utils.path_sanitizer import sanitize_string

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from aiohttp_retry import RetryClient


@dataclass
class DownloadingStatus:
    """
    Model for status of the download.

    Can be used in status update callbacks.
    """

    total_bytes: int | None
    downloaded_bytes: int
    name: str


@dataclass
class DownloadFileConfig:
    """General configuration for the file download"""

    session: RetryClient
    url: str

    filename: str
    destination: Path
    on_status_update: Callable[[DownloadingStatus], None] = lambda _: None

    guess_extension: bool = True


class DownloadFailureError(Exception):
    """Exception raised when the download failed for any reason"""


async def download_file(
    dl_config: DownloadFileConfig,
) -> Path:
    """Download files and report the downloading process via callback"""
    async with dl_config.session.get(dl_config.url) as response:
        if response.status != http.HTTPStatus.OK:
            raise DownloadFailureError

        filename = sanitize_string(dl_config.filename)
        file_path = dl_config.destination / filename

        content_type = response.content_type
        if content_type and dl_config.guess_extension:
            ext = mimetypes.guess_extension(content_type)
            if ext is not None:
                file_path = file_path.with_suffix(ext)

        total_downloaded = 0

        async with aiofiles.open(file_path, mode='wb') as file:
            total_size = response.content_length

            async for chunk in response.content.iter_chunked(524288):
                total_downloaded += len(chunk)
                dl_config.on_status_update(
                    DownloadingStatus(
                        name=filename,
                        total_bytes=total_size,
                        downloaded_bytes=total_downloaded,
                    ),
                )
                await file.write(chunk)

        return file_path
