"""A network timeout must be diagnosed as a timeout, not as a disk failure."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast

import pytest
from aiohttp import SocketTimeoutError

from boosty_downloader.infrastructure.file_downloader import (
    DownloadConnectionError,
    DownloadFileConfig,
    DownloadTimeoutError,
    download_file,
)

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


def _config(error: BaseException, destination: Path) -> DownloadFileConfig:
    return DownloadFileConfig(
        session=cast('RetryClient', _FakeSession(_FakeResponse(error))),
        url=URL,
        filename='clip.mp4',
        destination=destination,
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
    """The bug: a sock_read timeout surfaced as 'Failed during I/O operation',
    sending the user to check their disk instead of their network.
    """
    with pytest.raises(DownloadTimeoutError) as exc_info:
        await download_file(_config(error, tmp_path))

    assert 'timed out' in exc_info.value.message
    assert exc_info.value.resource_url == URL
    assert exc_info.value.file is not None, 'the partial file must be reported'


async def test_connection_reset_still_maps_to_connection_error(
    tmp_path: Path,
) -> None:
    """The new timeout branch must not swallow genuine connection failures."""
    with pytest.raises(DownloadConnectionError):
        await download_file(_config(ConnectionResetError(), tmp_path))
