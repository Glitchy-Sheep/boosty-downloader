"""Stream HTTP media into reserved destinations through owned temporary output."""

from __future__ import annotations

import http
import mimetypes
from asyncio import CancelledError
from asyncio import TimeoutError as AsyncioTimeoutError
from contextlib import AsyncExitStack, asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

from aiohttp import ClientConnectionError, ClientPayloadError
from yarl import URL

from boosty_downloader.infrastructure.media_publication import publish_completed_file
from boosty_downloader.infrastructure.media_workspace import (
    cleanup_media_workspaces,
    temporary_media_workspace,
)
from boosty_downloader.infrastructure.media_writer import open_media_writer
from boosty_downloader.infrastructure.path_sanitizer import (
    compose_filename,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
    from pathlib import Path

    from aiohttp import ClientResponse
    from aiohttp_retry import RetryClient

    from boosty_downloader.infrastructure.media_publication import PublishedFile
    from boosty_downloader.infrastructure.media_transfer import (
        MediaTarget,
        ReserveMediaPath,
    )
    from boosty_downloader.infrastructure.media_workspace import MediaWorkspace


_DEFAULT_CHUNK_SIZE_BYTES: Final = 2097152


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
class ReservedDownloadFileConfig:
    """HTTP media whose concrete destination is persisted before writing bytes."""

    session: RetryClient
    url: str
    filename: str
    reserve: ReserveMediaPath
    on_status_update: Callable[[DownloadingStatus], None] = lambda _: None
    guess_extension: bool = True
    chunk_size_bytes: int = _DEFAULT_CHUNK_SIZE_BYTES

    def __post_init__(self) -> None:
        """Reject chunk sizes that cannot consume the response body."""
        if self.chunk_size_bytes <= 0:
            message = 'HTTP media chunks must have a positive byte size'
            raise ValueError(message)


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
            'Download timed out: the server stopped sending data',
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
    return compose_filename(name, extension=guessed_ext or '')


def _author_filename(name: str) -> str:
    """Keep an author-given extension within the shared filename budget."""
    pure = PurePosixPath(name)
    return compose_filename(pure.stem, extension=pure.suffix)


# What a CDN answers on a dead signature; 403 can also mean genuinely
# no access - one refresh attempt safely tells the two apart.
_EXPIRED_LINK_STATUSES = frozenset(
    {http.HTTPStatus.BAD_REQUEST, http.HTTPStatus.FORBIDDEN}
)


def is_expired_link_error(error: BaseException | None) -> bool:
    """Check the error or its causes for a CDN answer typical of expired urls."""
    current = error
    while current is not None:
        if (
            isinstance(current, DownloadUnexpectedStatusError)
            and current.status_code in _EXPIRED_LINK_STATUSES
        ):
            return True
        current = current.__cause__
    return False


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


async def download_reserved_file(config: ReservedDownloadFileConfig) -> PublishedFile:
    """
    Reserve a concrete HTTP filename, then publish only its completed output.

    The owner stops any earlier writer of this piece before calling. Reservation failures propagate unchanged. Transfer errors never identify a final file for deletion.
    """
    async with open_download_response(config.session, config.url) as response:
        filename = response_filename(
            response, config.filename, guess_extension=config.guess_extension
        )
        target = config.reserve(filename)
        with download_errors(config.url):
            return await _transfer_reserved_response(response, config, target)


@asynccontextmanager
async def open_download_response(
    session: RetryClient, url: str, *, encoded_url: bool = False
) -> AsyncGenerator[ClientResponse, None]:
    """Acquire an accepted HTTP response without translating errors from its consumer."""
    async with AsyncExitStack() as stack:
        with download_errors(url):
            request_url = URL(url, encoded=True) if encoded_url else url
            response = await stack.enter_async_context(session.get(request_url))
            _require_success(response, url)
        yield response


def _require_success(response: ClientResponse, url: str) -> None:
    if response.status != http.HTTPStatus.OK:
        raise DownloadUnexpectedStatusError(
            resource_url=url,
            status=response.status,
            response_message=response.reason or 'No reason provided',
        )


def response_filename(
    response: ClientResponse, filename: str, *, guess_extension: bool = True
) -> str:
    """Resolve a portable basename using the response type for app-built names."""
    if guess_extension:
        return _app_built_filename(
            filename, _extension_to_append(response.content_type)
        )
    return _author_filename(filename)


async def copy_download_response(
    response: ClientResponse,
    write: Callable[[bytes], Awaitable[object]],
    *,
    filename: str,
    on_status_update: Callable[[DownloadingStatus], None] = lambda _: None,
    chunk_size_bytes: int = _DEFAULT_CHUNK_SIZE_BYTES,
) -> None:
    """Stream bounded chunks into a writer and report consumed response bytes."""
    if chunk_size_bytes <= 0:
        message = 'HTTP media chunks must have a positive byte size'
        raise ValueError(message)
    total_downloaded = 0
    async for chunk in response.content.iter_chunked(chunk_size_bytes):
        total_downloaded += len(chunk)
        on_status_update(
            DownloadingStatus(
                name=filename,
                total_bytes=response.content_length,
                total_downloaded_bytes=total_downloaded,
                downloaded_bytes=len(chunk),
            )
        )
        await write(chunk)


async def _transfer_reserved_response(
    response: ClientResponse, config: ReservedDownloadFileConfig, target: MediaTarget
) -> PublishedFile:
    cleanup_media_workspaces(
        target.library_root,
        target.post_folder,
        target.relative_path,
        media_id=target.media_id,
    )
    with temporary_media_workspace(
        target.library_root,
        target.post_folder,
        target.relative_path,
        media_id=target.media_id,
    ) as workspace:
        return await _write_reserved_response(response, config, workspace)


async def _write_reserved_response(
    response: ClientResponse,
    config: ReservedDownloadFileConfig,
    workspace: MediaWorkspace,
) -> PublishedFile:
    source = workspace.directory / 'download.tmp'
    async with open_media_writer(source) as writer:
        await copy_download_response(
            response,
            writer.write,
            filename=workspace.destination.name,
            on_status_update=config.on_status_update,
            chunk_size_bytes=config.chunk_size_bytes,
        )
    return publish_completed_file(source, workspace.destination)


@contextmanager
def download_errors(url: str) -> Generator[None, None, None]:
    """Translate HTTP and output failures while preserving their original causes."""
    try:
        yield
    except (CancelledError, KeyboardInterrupt) as error:
        raise DownloadCancelledError(resource_url=url) from error
    except (TimeoutError, AsyncioTimeoutError) as error:
        raise DownloadTimeoutError(resource_url=url) from error
    except (
        ConnectionResetError,
        BrokenPipeError,
        ClientConnectionError,
        ClientPayloadError,
    ) as error:
        raise DownloadConnectionError(resource_url=url) from error
    except OSError as error:
        raise DownloadIOFailureError(resource_url=url) from error
