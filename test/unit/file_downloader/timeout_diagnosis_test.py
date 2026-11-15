"""A network timeout must be diagnosed as a timeout, not as a disk failure."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest
from aiohttp import SocketTimeoutError

from boosty_downloader.infrastructure.file_downloader import (
    DownloadConnectionError,
    DownloadTimeoutError,
    ReservedDownloadFileConfig,
    download_reserved_file,
)
from boosty_downloader.infrastructure.media_transfer import MediaTarget

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from aiohttp_retry import RetryClient

URL = 'https://cdn.example/file'


class _FakeContent:
    """Streams one chunk, then raises the prepared error."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        del size

        async def _stream() -> AsyncIterator[bytes]:
            yield b'first chunk'
            raise self._error

        return _stream()


class _FakeResponse:
    status = 200
    reason = 'OK'
    content_length = None

    def __init__(self, error: BaseException) -> None:
        self.content = _FakeContent(error)


class _FakeRequestContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeSession:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    def get(self, url: str) -> _FakeRequestContext:
        del url
        return _FakeRequestContext(self._response)


def _config(error: BaseException, destination: Path) -> ReservedDownloadFileConfig:
    return ReservedDownloadFileConfig(
        session=cast('RetryClient', _FakeSession(_FakeResponse(error))),
        url=URL,
        filename='clip.mp4',
        reserve=lambda name: MediaTarget(
            destination, 'author/post', f'files/{name}', 'file:clip'
        ),
        guess_extension=False,
    )


@pytest.mark.parametrize(
    'error',
    [TimeoutError('read timed out'), asyncio.TimeoutError(), SocketTimeoutError()],
    ids=['builtin', 'asyncio', 'aiohttp-sock-read'],
)
async def test_mid_download_timeout_is_reported_as_a_timeout(
    tmp_path: Path, error: BaseException
) -> None:
    """Read timeouts retain their network diagnosis and leave no final media."""
    with pytest.raises(DownloadTimeoutError) as exc_info:
        await download_reserved_file(_config(error, tmp_path))

    assert 'timed out' in exc_info.value.message
    assert exc_info.value.resource_url == URL
    assert exc_info.value.file is None
    assert exc_info.value.__cause__ is error
    assert not (tmp_path / 'author/post/files/clip.mp4').exists()


async def test_connection_reset_still_maps_to_connection_error(
    tmp_path: Path,
) -> None:
    """Connection failures retain their separate diagnosis."""
    with pytest.raises(DownloadConnectionError):
        await download_reserved_file(_config(ConnectionResetError(), tmp_path))
