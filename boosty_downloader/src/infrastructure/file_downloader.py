"""Module to download files with reporting process mechanisms"""

from __future__ import annotations

import http
import mimetypes
from asyncio import CancelledError
from dataclasses import dataclass
from pathlib import PurePath
from typing import TYPE_CHECKING

import aiofiles
from aiohttp import ClientConnectionError, ClientPayloadError

from boosty_downloader.src.infrastructure.path_sanitizer import (
    sanitize_filename,
)

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

    name: str
    total_bytes: int | None
    total_downloaded_bytes: int
    downloaded_bytes: int = 0


@dataclass
class DownloadFileConfig:
    """General configuration for the file download"""

    session: RetryClient
    url: str

    filename: str
    destination: Path
    on_status_update: Callable[[DownloadingStatus], None] = lambda _: None

    # True only when the caller builds the filename without an extension
    # (videos, images). Names that come from the author (files, audio)
    # already carry their extension and must never be touched.
    guess_extension: bool = True
    chunk_size_bytes: int = 524288  # 512 KiB


class DownloadError(Exception):
    """Exception raised when the download failed for any reason"""

    message: str
    file: Path | None
    resource_url: str

    def __init__(self, message: str, file: Path | None, resource_url: str) -> None:
        super().__init__(message)
        self.message = message
        self.file = file
        self.resource_url = resource_url


class DownloadCancelledError(DownloadError):
    """Exception raised when the download was cancelled by the user"""

    def __init__(self, resource_url: str, file: Path | None = None) -> None:
        super().__init__('Download cancelled by user', file, resource_url=resource_url)


class DownloadTimeoutError(DownloadError):
    """Exception raised when the download timed out"""

    def __init__(self, resource_url: str, file: Path | None = None) -> None:
        super().__init__(
            'Download timed out for the destination server',
            file,
            resource_url=resource_url,
        )


class DownloadConnectionError(DownloadError):
    """Exception raised when there was a connection error during the download"""

    def __init__(self, resource_url: str, file: Path | None = None) -> None:
        super().__init__(
            'Connection error during the download', file, resource_url=resource_url
        )


class DownloadIOFailureError(DownloadError):
    """Exception raised when there was an IOError during the download"""

    def __init__(self, resource_url: str, file: Path | None = None) -> None:
        super().__init__('Failed during I/O operation', file, resource_url=resource_url)


class DownloadUnexpectedStatusError(DownloadError):
    """Exception raised when the server returned an unexpected status code"""

    status_code: int
    response_message: str

    def __init__(self, status: int, response_message: str, resource_url: str) -> None:
        super().__init__(
            f'Unexpected status code: {status}', file=None, resource_url=resource_url
        )
        self.status_code = status
        self.response_message = response_message


def _app_built_filename(name: str, guessed_ext: str | None) -> str:
    """App-built names (videos, images): the guessed extension is glued on."""
    return sanitize_filename(name, suffix=guessed_ext or '')


def _author_filename(name: str) -> str:
    """Truncate an author-given name; its own extension always survives."""
    pure = PurePath(name)
    ext = pure.suffix
    return sanitize_filename(pure.stem, suffix=sanitize_filename(ext) if ext else '')


def _extension_to_append(content_type: str | None) -> str | None:
    """
    Pick an extension for a name that has none by construction.

    Only callers whose filenames are built without an extension (videos,
    images) ask for this. 'application/octet-stream' ("bytes, type
    unknown") teaches nothing - no ".bin" is ever born out of it.
    """
    if not content_type or content_type == 'application/octet-stream':
        return None
    return mimetypes.guess_extension(content_type)


async def download_file(
    dl_config: DownloadFileConfig,
) -> Path:
    """Download files and report the downloading process via callback"""
    async with dl_config.session.get(dl_config.url) as response:
        if response.status != http.HTTPStatus.OK:
            raise DownloadUnexpectedStatusError(
                resource_url=dl_config.url,
                status=response.status,
                response_message=response.reason or 'No reason provided',
            )

        if dl_config.guess_extension:
            filename = _app_built_filename(
                dl_config.filename, _extension_to_append(response.content_type)
            )
        else:
            filename = _author_filename(dl_config.filename)
        file_path = dl_config.destination / filename

        total_downloaded = 0

        async with aiofiles.open(file_path, mode='wb') as file:
            total_size = response.content_length

            try:
                async for chunk in response.content.iter_chunked(
                    dl_config.chunk_size_bytes
                ):
                    total_downloaded += len(chunk)
                    dl_config.on_status_update(
                        DownloadingStatus(
                            name=filename,
                            total_bytes=total_size,
                            total_downloaded_bytes=total_downloaded,
                            downloaded_bytes=len(chunk),
                        ),
                    )
                    await file.write(chunk)
            except (CancelledError, KeyboardInterrupt) as e:
                raise DownloadCancelledError(
                    file=file_path, resource_url=dl_config.url
                ) from e
            except DownloadTimeoutError as e:
                raise DownloadTimeoutError(
                    file=file_path, resource_url=dl_config.url
                ) from e
            except (
                ConnectionResetError,
                BrokenPipeError,
                ClientConnectionError,
                ClientPayloadError,
            ) as e:
                raise DownloadConnectionError(
                    file=file_path, resource_url=dl_config.url
                ) from e
            except OSError as e:
                raise DownloadIOFailureError(
                    file=file_path, resource_url=dl_config.url
                ) from e

        return file_path
