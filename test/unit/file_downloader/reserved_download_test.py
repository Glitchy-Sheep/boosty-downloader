"""HTTP transfers reserve persisted names before writing owned temporary output."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest
from aiohttp import ClientPayloadError, ClientTimeout, SocketTimeoutError, web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient

from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadConnectionError,
    DownloadingStatus,
    DownloadIOFailureError,
    DownloadTimeoutError,
    DownloadUnexpectedStatusError,
    ReservedDownloadFileConfig,
    download_reserved_file,
    is_expired_link_error,
)
from boosty_downloader.infrastructure.media_transfer import MediaTarget
from boosty_downloader.infrastructure.media_workspace import temporary_media_workspace

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable
    from pathlib import Path

PAYLOAD = b'complete-media-bytes'
POST_FOLDER = 'author/post'
MEDIA_ID = 'file:payload'


@dataclass(frozen=True)
class _HttpClient:
    session: RetryClient
    url: str


@asynccontextmanager
async def _client(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    timeout: ClientTimeout | None = None,
) -> AsyncGenerator[_HttpClient, None]:
    app = web.Application()
    app.router.add_get('/payload', handler)
    async with (
        TestServer(app) as server,
        RetryClient(
            timeout=timeout,
            retry_options=ExponentialRetry(attempts=1),
        ) as session,
    ):
        yield _HttpClient(session, str(server.make_url('/payload')))


async def _payload(_: web.Request) -> web.Response:
    return web.Response(body=PAYLOAD, content_type='video/mp4')


def _target(root: Path, name: str) -> MediaTarget:
    return MediaTarget(root, POST_FOLDER, f'files/{name}', MEDIA_ID)


def _config(client: _HttpClient, root: Path) -> ReservedDownloadFileConfig:
    return ReservedDownloadFileConfig(
        session=client.session,
        url=client.url,
        filename='movie',
        reserve=lambda name: _target(root, name),
    )


def _assert_no_workspaces(root: Path) -> None:
    assert not list(root.rglob('.boosty-*.part'))


def _assert_no_output(root: Path) -> None:
    _assert_no_workspaces(root)
    assert not list(root.rglob('movie.mp4'))


async def test_reservation_precedes_output_and_progress_uses_the_reserved_name(
    tmp_path: Path,
) -> None:
    root = tmp_path / 'library'
    reserved: list[str] = []
    updates: list[DownloadingStatus] = []

    def reserve(name: str) -> MediaTarget:
        assert not root.exists()
        reserved.append(name)
        return _target(root, 'movie (another).mp4')

    def progress(status: DownloadingStatus) -> None:
        assert reserved == ['movie.mp4']
        assert not (root / POST_FOLDER / 'files/movie (another).mp4').exists()
        updates.append(status)

    async with _client(_payload) as client:
        result = await download_reserved_file(
            replace(
                _config(client, root),
                reserve=reserve,
                on_status_update=progress,
                chunk_size_bytes=4,
            )
        )

    assert result.path == root / POST_FOLDER / 'files/movie (another).mp4'
    assert result.path.read_bytes() == PAYLOAD
    assert result.size == len(PAYLOAD)
    assert sum(update.downloaded_bytes for update in updates) == len(PAYLOAD)
    assert updates[-1].total_downloaded_bytes == len(PAYLOAD)
    assert all(update.total_bytes == len(PAYLOAD) for update in updates)
    assert all(update.name == result.path.name for update in updates)
    assert not list(root.rglob('.boosty-*.part'))


async def test_failed_record_save_escapes_unchanged_without_media_writes(
    tmp_path: Path,
) -> None:
    root = tmp_path / 'library'
    failure = OSError('Cannot save pending record')

    def reserve(_name: str) -> MediaTarget:
        raise failure

    async with _client(_payload) as client:
        with pytest.raises(OSError, match='Cannot save pending record') as caught:
            await download_reserved_file(
                replace(_config(client, root), reserve=reserve)
            )

    assert caught.value is failure
    assert not root.exists()


@pytest.mark.parametrize(
    ('name', 'content_type', 'guess_extension', 'expected'),
    [
        ('lecture.v1', 'video/mp4', True, 'lecture.v1.mp4'),
        ('report.tar.gz', 'video/mp4', False, 'report.tar.gz'),
        ('picture', 'image/png', True, 'picture.png'),
        ('unknown', 'application/octet-stream', True, 'unknown'),
        ('CON.txt', 'application/octet-stream', False, '_CON.txt'),
    ],
)
async def test_reservation_receives_the_concrete_portable_basename(
    tmp_path: Path,
    name: str,
    content_type: str,
    *,
    guess_extension: bool,
    expected: str,
) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=PAYLOAD, content_type=content_type)

    reserved: list[str] = []

    def reserve(name: str) -> MediaTarget:
        reserved.append(name)
        return _target(tmp_path, name)

    async with _client(handler) as client:
        result = await download_reserved_file(
            replace(
                _config(client, tmp_path),
                filename=name,
                guess_extension=guess_extension,
                reserve=reserve,
            )
        )

    assert reserved == [expected]
    assert result.path.name == expected
    assert result.path.read_bytes() == PAYLOAD


async def test_rejected_response_never_reserves_a_destination(tmp_path: Path) -> None:
    root = tmp_path / 'library'

    async def handler(_: web.Request) -> web.Response:
        return web.Response(status=403)

    def reserve(_name: str) -> MediaTarget:
        pytest.fail('A rejected response must not reserve output')

    async with _client(handler) as client:
        with pytest.raises(DownloadUnexpectedStatusError) as caught:
            await download_reserved_file(
                replace(_config(client, root), reserve=reserve)
            )

    assert is_expired_link_error(caught.value)
    assert caught.value.file is None
    assert not root.exists()


async def test_occupied_final_file_is_preserved_and_not_reported_for_deletion(
    tmp_path: Path,
) -> None:
    destination = tmp_path / POST_FOLDER / 'files/movie.mp4'
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b'user file')

    async with _client(_payload) as client:
        with pytest.raises(DownloadIOFailureError) as caught:
            await download_reserved_file(_config(client, tmp_path))

    assert isinstance(caught.value.__cause__, FileExistsError)
    assert caught.value.file is None
    assert destination.read_bytes() == b'user file'
    _assert_no_workspaces(tmp_path)


async def test_final_file_created_during_transfer_is_not_replaced(
    tmp_path: Path,
) -> None:
    destination = tmp_path / POST_FOLDER / 'files/movie.mp4'

    def progress(_status: DownloadingStatus) -> None:
        destination.write_bytes(b'user file')

    async with _client(_payload) as client:
        with pytest.raises(DownloadIOFailureError) as caught:
            await download_reserved_file(
                replace(_config(client, tmp_path), on_status_update=progress)
            )

    assert isinstance(caught.value.__cause__, FileExistsError)
    assert caught.value.file is None
    assert destination.read_bytes() == b'user file'
    _assert_no_workspaces(tmp_path)


async def test_retry_cleans_only_the_previous_owned_workspace(tmp_path: Path) -> None:
    with temporary_media_workspace(
        tmp_path, POST_FOLDER, 'files/movie.mp4', media_id=MEDIA_ID
    ) as workspace:
        (workspace.directory / 'download.tmp').write_bytes(b'partial')
        stale = workspace.directory.with_name('.boosty-stopped.part')
        workspace.directory.rename(stale)
    foreign = stale.parent / '.unrelated.part'
    foreign.write_bytes(b'keep')

    async with _client(_payload) as client:
        result = await download_reserved_file(_config(client, tmp_path))

    assert result.path.read_bytes() == PAYLOAD
    assert not stale.exists()
    assert foreign.read_bytes() == b'keep'


async def test_cancellation_cleans_partial_output_before_returning(
    tmp_path: Path,
) -> None:
    sent = asyncio.Event()
    stop = asyncio.Event()

    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={'Content-Type': 'video/mp4'})
        await response.prepare(request)
        await response.write(b'first chunk')
        await stop.wait()
        return response

    def progress(_status: DownloadingStatus) -> None:
        sent.set()

    async with _client(handler) as client:
        config = replace(_config(client, tmp_path), on_status_update=progress)
        task = asyncio.create_task(download_reserved_file(config))
        try:
            await asyncio.wait_for(sent.wait(), timeout=2)
            task.cancel()
            with pytest.raises(DownloadCancelledError) as caught:
                await asyncio.wait_for(task, timeout=2)
        finally:
            stop.set()

    assert isinstance(caught.value.__cause__, asyncio.CancelledError)
    assert caught.value.file is None
    _assert_no_output(tmp_path)


@pytest.mark.parametrize('before_headers', [False, True])
async def test_http_timeout_is_classified_without_leaving_final_output(
    tmp_path: Path, *, before_headers: bool
) -> None:
    stop = asyncio.Event()

    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={'Content-Type': 'video/mp4'})
        if not before_headers:
            await response.prepare(request)
            await response.write(b'first chunk')
        await stop.wait()
        return response

    async with _client(handler, timeout=ClientTimeout(sock_read=0.03)) as client:
        try:
            with pytest.raises(DownloadTimeoutError) as caught:
                await download_reserved_file(_config(client, tmp_path))
        finally:
            stop.set()

    assert isinstance(caught.value.__cause__, SocketTimeoutError)
    assert caught.value.file is None
    _assert_no_output(tmp_path)


async def test_truncated_response_is_not_published(tmp_path: Path) -> None:
    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            headers={'Content-Type': 'video/mp4', 'Content-Length': '100'}
        )
        await response.prepare(request)
        await response.write(b'partial')
        assert request.transport is not None
        request.transport.close()
        return response

    async with _client(handler) as client:
        with pytest.raises(DownloadConnectionError) as caught:
            await download_reserved_file(_config(client, tmp_path))

    assert isinstance(caught.value.__cause__, ClientPayloadError)
    assert caught.value.file is None
    _assert_no_output(tmp_path)


async def test_media_request_uses_only_the_supplied_credential_free_session(
    tmp_path: Path,
) -> None:
    headers: dict[str, str] = {}

    async def handler(request: web.Request) -> web.Response:
        headers.update(request.headers)
        return await _payload(request)

    async with _client(handler) as client:
        await download_reserved_file(_config(client, tmp_path))

    assert 'Authorization' not in headers
    assert 'Cookie' not in headers


@pytest.mark.parametrize('chunk_size', [0, -1])
async def test_invalid_chunk_size_cannot_publish_an_unread_response(
    tmp_path: Path, chunk_size: int
) -> None:
    root = tmp_path / 'library'
    requested = False

    async def handler(request: web.Request) -> web.Response:
        nonlocal requested
        requested = True
        return await _payload(request)

    async with _client(handler) as client:
        with pytest.raises(ValueError, match='positive byte size'):
            await download_reserved_file(
                replace(_config(client, root), chunk_size_bytes=chunk_size)
            )

    assert not requested
    assert not root.exists()
