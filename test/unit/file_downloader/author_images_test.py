"""Author images are refreshed atomically through the shared HTTP transport."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from errno import EACCES, ENOSYS, EPERM
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, BinaryIO, Literal

import pytest
from aiohttp import ClientTimeout, NonHttpUrlClientError, TooManyRedirects, web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient

from boosty_downloader.infrastructure import author_images, media_writer
from boosty_downloader.infrastructure.author_images import (
    AuthorImageKind,
    download_author_image,
)
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadConnectionError,
    DownloadError,
    DownloadIOFailureError,
    DownloadTimeoutError,
    DownloadUnexpectedStatusError,
)
from boosty_downloader.infrastructure.media_workspace import temporary_owned_workspace

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from aiohttp import ClientResponse

PAYLOAD = b'complete-image-bytes'
PREVIOUS = b'previous avatar'
AUTHOR = 'test-author'
SERVICE_FOLDER = '.boosty-downloader'


@dataclass(frozen=True, slots=True)
class _HttpClient:
    session: RetryClient
    url: str

    async def download(
        self, root: Path, kind: AuthorImageKind = AuthorImageKind.avatar
    ) -> str:
        return await download_author_image(
            session=self.session,
            library_root=root,
            author=AUTHOR,
            kind=kind,
            url=self.url,
        )


@asynccontextmanager
async def _client(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    timeout: ClientTimeout | None = None,
) -> AsyncGenerator[_HttpClient, None]:
    app = web.Application()
    app.router.add_get('/image', handler)
    async with (
        TestServer(app) as server,
        RetryClient(
            timeout=timeout, retry_options=ExponentialRetry(attempts=1)
        ) as session,
    ):
        yield _HttpClient(session, str(server.make_url('/image')))


async def _payload(_: web.Request) -> web.Response:
    return web.Response(body=PAYLOAD, content_type='image/png')


def _prior_image(root: Path) -> Path:
    path = root / AUTHOR / SERVICE_FOLDER / 'avatar.png'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(PREVIOUS)
    return path


def _assert_clean(root: Path) -> None:
    assert not _workspaces(root)


def _workspaces(root: Path) -> list[Path]:
    return list(root.rglob('.boosty-*.part'))


def _assert_empty(root: Path) -> None:
    assert list(root.iterdir()) == []


def _symlink(link: Path, target: Path, *, is_directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_directory)
    except NotImplementedError:
        pytest.skip('Filesystem does not support symlinks')
    except OSError as error:
        if (
            error.errno in {EPERM, EACCES, ENOSYS}
            or getattr(error, 'winerror', None) == 1314
        ):
            pytest.skip('Filesystem does not permit symlinks')
        raise


@pytest.mark.parametrize('kind', list(AuthorImageKind))
@pytest.mark.parametrize(
    ('content_type', 'extension'),
    [('image/png', '.png'), ('image/jpeg', '.jpg'), ('application/octet-stream', '')],
)
async def test_image_role_and_response_type_determine_the_relative_path(
    tmp_path: Path, kind: AuthorImageKind, content_type: str, extension: str
) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=PAYLOAD, content_type=content_type)

    async with _client(handler) as client:
        result = await client.download(tmp_path, kind)

    assert result == f'{SERVICE_FOLDER}/{kind.value}{extension}'
    assert (tmp_path / AUTHOR / result).read_bytes() == PAYLOAD
    _assert_clean(tmp_path)


async def test_refresh_replaces_only_the_owned_path_and_preserves_hardlinks(
    tmp_path: Path,
) -> None:
    previous = _prior_image(tmp_path)
    linked = previous.with_name('keep.png')
    linked.hardlink_to(previous)
    old_extension = previous.with_suffix('.jpg')
    old_extension.write_bytes(b'older format')
    foreign = previous.with_name('notes.txt')
    foreign.write_bytes(b'keep notes')

    async with _client(_payload) as client:
        await client.download(tmp_path)

    assert previous.read_bytes() == PAYLOAD
    assert linked.read_bytes() == PREVIOUS
    assert old_extension.read_bytes() == b'older format'
    assert foreign.read_bytes() == b'keep notes'
    _assert_clean(tmp_path)


@pytest.mark.parametrize('status', [403, 404, 500])
async def test_rejected_response_preserves_previous_image(
    tmp_path: Path, status: int
) -> None:
    previous = _prior_image(tmp_path)
    timestamp = previous.stat().st_mtime_ns

    async def handler(_: web.Request) -> web.Response:
        return web.Response(status=status)

    async with _client(handler) as client:
        with pytest.raises(DownloadUnexpectedStatusError) as caught:
            await client.download(tmp_path)

    assert caught.value.status_code == status
    assert previous.read_bytes() == PREVIOUS
    assert previous.stat().st_mtime_ns == timestamp
    _assert_clean(tmp_path)


async def test_incomplete_body_preserves_the_previous_image(tmp_path: Path) -> None:
    previous = _prior_image(tmp_path)

    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            headers={'Content-Type': 'image/png', 'Content-Length': '100'}
        )
        await response.prepare(request)
        await response.write(b'partial')
        assert request.transport is not None
        request.transport.close()
        return response

    async with _client(handler) as client:
        with pytest.raises(DownloadConnectionError):
            await client.download(tmp_path)

    assert previous.read_bytes() == PREVIOUS
    _assert_clean(tmp_path)


async def test_empty_response_preserves_the_previous_image(tmp_path: Path) -> None:
    previous = _prior_image(tmp_path)
    timestamp = previous.stat().st_mtime_ns

    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=b'', content_type='image/png')

    async with _client(handler) as client:
        with pytest.raises(DownloadError, match='Image response is empty'):
            await client.download(tmp_path)

    assert previous.read_bytes() == PREVIOUS
    assert previous.stat().st_mtime_ns == timestamp
    assert list(previous.parent.iterdir()) == [previous]
    _assert_clean(tmp_path)


@pytest.mark.parametrize('before_headers', [False, True])
async def test_timeout_preserves_the_previous_image(
    tmp_path: Path, *, before_headers: bool
) -> None:
    previous = _prior_image(tmp_path)
    release = asyncio.Event()

    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={'Content-Type': 'image/png'})
        if not before_headers:
            await response.prepare(request)
            await response.write(b'partial')
        await release.wait()
        return response

    async with _client(handler, timeout=ClientTimeout(sock_read=0.03)) as client:
        try:
            with pytest.raises(DownloadTimeoutError):
                await client.download(tmp_path)
        finally:
            release.set()

    assert previous.read_bytes() == PREVIOUS
    _assert_clean(tmp_path)


@pytest.mark.parametrize('phase', ['write', 'close', 'publish'])
async def test_io_failure_preserves_previous_image_and_original_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: Literal['write', 'close', 'publish'],
) -> None:
    previous = _prior_image(tmp_path)
    failure = OSError('Test output failure')

    async def fail_write(_self: media_writer.MediaWriter, _data: bytes) -> None:
        raise failure

    def fail_close(file: BinaryIO) -> None:
        file.close()
        raise failure

    def fail_publish(_self: Path, _destination: Path) -> Path:
        raise failure

    match phase:
        case 'write':
            monkeypatch.setattr(media_writer.MediaWriter, 'write', fail_write)
        case 'close':
            monkeypatch.setattr(media_writer, '_close_file', fail_close)
        case 'publish':
            monkeypatch.setattr(Path, 'replace', fail_publish)

    async with _client(_payload) as client:
        with pytest.raises(DownloadIOFailureError) as caught:
            await client.download(tmp_path)

    assert caught.value.__cause__ is failure
    assert caught.value.file is None
    assert previous.read_bytes() == PREVIOUS
    _assert_clean(tmp_path)


async def test_cancellation_waits_for_close_before_cleaning_and_keeps_previous_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = _prior_image(tmp_path)
    entered = asyncio.Event()
    release = Event()
    loop = asyncio.get_running_loop()
    files: list[BinaryIO] = []

    def gated_close(file: BinaryIO) -> None:
        files.append(file)
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(timeout=5):
            message = 'Test did not release the file worker'
            raise TimeoutError(message)
        file.close()

    monkeypatch.setattr(media_writer, '_close_file', gated_close)
    async with _client(_payload) as client:
        task = asyncio.create_task(client.download(tmp_path))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert _workspaces(tmp_path)
            assert previous.read_bytes() == PREVIOUS
        finally:
            release.set()
        with pytest.raises(DownloadCancelledError) as caught:
            await asyncio.wait_for(task, timeout=2)

    assert isinstance(caught.value.__cause__, asyncio.CancelledError)
    assert all(file.closed for file in files)
    assert previous.read_bytes() == PREVIOUS
    _assert_clean(tmp_path)


@pytest.mark.parametrize('outside_exists', [False, True])
async def test_final_symlink_is_refused_without_touching_its_target(
    tmp_path: Path, *, outside_exists: bool
) -> None:
    root = tmp_path / 'library'
    target = tmp_path / 'outside.png'
    if outside_exists:
        target.write_bytes(b'keep outside')
    destination = root / AUTHOR / SERVICE_FOLDER / 'avatar.png'
    destination.parent.mkdir(parents=True)
    _symlink(destination, target)

    async with _client(_payload) as client:
        with pytest.raises(DownloadError) as caught:
            await client.download(root)

    assert isinstance(caught.value.__cause__, ValueError)
    assert destination.is_symlink()
    assert target.exists() == outside_exists
    if outside_exists:
        assert target.read_bytes() == b'keep outside'
    _assert_clean(root)


@pytest.mark.parametrize('linked_folder', ['author', 'service'])
async def test_escaping_directory_link_is_rejected_before_writing(
    tmp_path: Path, linked_folder: Literal['author', 'service']
) -> None:
    root = tmp_path / 'library'
    outside = tmp_path / 'outside'
    outside.mkdir()
    match linked_folder:
        case 'author':
            link = root / AUTHOR
        case 'service':
            link = root / AUTHOR / SERVICE_FOLDER
    link.parent.mkdir(parents=True)
    _symlink(link, outside, is_directory=True)

    async with _client(_payload) as client:
        with pytest.raises(DownloadError) as caught:
            await client.download(root)

    assert isinstance(caught.value.__cause__, ValueError)
    _assert_empty(outside)
    _assert_clean(root)


@pytest.mark.parametrize('author', ['../outside', '', 'CON', 'author/../another'])
async def test_unsafe_author_never_creates_a_directory(
    tmp_path: Path, author: str
) -> None:
    async with _client(_payload) as client:
        with pytest.raises(DownloadError) as caught:
            await download_author_image(
                session=client.session,
                library_root=tmp_path,
                author=author,
                kind=AuthorImageKind.avatar,
                url=client.url,
            )

    assert isinstance(caught.value.__cause__, ValueError)
    _assert_empty(tmp_path)


async def test_retry_removes_only_owned_stopped_workspaces(tmp_path: Path) -> None:
    previous = _prior_image(tmp_path)
    with temporary_owned_workspace(
        previous.parent, owner_id='author-image:avatar'
    ) as directory:
        (directory / 'download.tmp').write_bytes(b'partial')
        stale = directory.with_name('.boosty-stopped.part')
        directory.rename(stale)
    foreign = previous.parent / '.boosty-foreign.part'
    foreign.mkdir()
    (foreign / 'download.tmp').write_bytes(b'keep foreign')
    with temporary_owned_workspace(
        previous.parent, owner_id='author-image:cover'
    ) as cover_workspace:
        async with _client(_payload) as client:
            await client.download(tmp_path)
        assert cover_workspace.is_dir()

    assert previous.read_bytes() == PAYLOAD
    assert not stale.exists()
    assert (foreign / 'download.tmp').read_bytes() == b'keep foreign'


async def test_publication_rechecks_the_final_entry_after_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    previous = _prior_image(tmp_path)
    outside = tmp_path / 'outside.png'
    outside.write_bytes(b'keep outside')
    original_write = media_writer.MediaWriter.write

    async def change_destination(writer: media_writer.MediaWriter, data: bytes) -> None:
        await original_write(writer, data)
        previous.unlink()
        _symlink(previous, outside)

    monkeypatch.setattr(media_writer.MediaWriter, 'write', change_destination)
    async with _client(_payload) as client:
        with pytest.raises(DownloadError):
            await client.download(tmp_path)

    assert previous.is_symlink()
    assert outside.read_bytes() == b'keep outside'
    _assert_clean(tmp_path)


async def test_publication_rechecks_author_containment_after_streaming(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'library'
    _prior_image(root)
    outside = tmp_path / 'moved-author'
    author_folder = root / AUTHOR

    def move_author(file: BinaryIO) -> None:
        file.close()
        author_folder.rename(outside)
        _symlink(author_folder, outside, is_directory=True)

    monkeypatch.setattr(media_writer, '_close_file', move_author)
    async with _client(_payload) as client:
        with pytest.raises(DownloadError):
            await client.download(root)

    assert (outside / SERVICE_FOLDER / 'avatar.png').read_bytes() == PREVIOUS
    _assert_clean(outside)


async def test_existing_directory_cannot_be_claimed_as_an_image(tmp_path: Path) -> None:
    destination = tmp_path / AUTHOR / SERVICE_FOLDER / 'avatar.png'
    destination.mkdir(parents=True)
    foreign = destination / 'notes.txt'
    foreign.write_bytes(b'keep notes')

    async with _client(_payload) as client:
        with pytest.raises(DownloadError):
            await client.download(tmp_path)

    assert foreign.read_bytes() == b'keep notes'
    _assert_clean(tmp_path)


async def test_image_request_uses_only_the_supplied_media_session(
    tmp_path: Path,
) -> None:
    headers: dict[str, str] = {}

    async def handler(request: web.Request) -> web.Response:
        headers.update(request.headers)
        return await _payload(request)

    async with _client(handler) as client:
        await client.download(tmp_path)

    assert 'Authorization' not in headers
    assert 'Cookie' not in headers


@pytest.mark.parametrize(
    'failure', [OSError('Response close failed'), asyncio.CancelledError()]
)
async def test_response_close_failure_never_publishes_the_completed_temporary_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    previous = _prior_image(tmp_path)
    open_response = author_images.open_download_response

    @asynccontextmanager
    async def failed_close(
        session: RetryClient, url: str
    ) -> AsyncGenerator[ClientResponse, None]:
        async with open_response(session, url) as response:
            yield response
        raise failure

    monkeypatch.setattr(author_images, 'open_download_response', failed_close)
    async with _client(_payload) as client:
        with pytest.raises(DownloadError) as caught:
            await client.download(tmp_path)

    assert caught.value.__cause__ is failure
    assert previous.read_bytes() == PREVIOUS
    _assert_clean(tmp_path)


async def test_redirect_loop_preserves_previous_image_and_keeps_url_out_of_message(
    tmp_path: Path,
) -> None:
    previous = _prior_image(tmp_path)
    timestamp = previous.stat().st_mtime_ns
    requested = 0
    signature = 'private-image-signature'

    async def redirect(_: web.Request) -> web.Response:
        nonlocal requested
        requested += 1
        return web.Response(
            status=302, headers={'Location': f'/image?signature={signature}'}
        )

    async with _client(redirect) as client:
        signed_client = _HttpClient(
            client.session, f'{client.url}?signature={signature}'
        )
        with pytest.raises(DownloadError) as caught:
            await signed_client.download(tmp_path)

    assert requested > 1
    assert isinstance(caught.value.__cause__, TooManyRedirects)
    assert str(caught.value) == 'Author image request failed'
    assert signature not in str(caught.value)
    assert caught.value.file is None
    assert previous.read_bytes() == PREVIOUS
    assert previous.stat().st_mtime_ns == timestamp
    _assert_clean(tmp_path)


async def test_non_http_url_preserves_previous_image_and_keeps_url_out_of_message(
    tmp_path: Path,
) -> None:
    previous = _prior_image(tmp_path)
    timestamp = previous.stat().st_mtime_ns
    signature = 'private-image-signature'
    url = f'ftp://example.invalid/avatar.png?signature={signature}'
    async with RetryClient(retry_options=ExponentialRetry(attempts=1)) as session:
        with pytest.raises(DownloadError) as caught:
            await _HttpClient(session, url).download(tmp_path)

    assert isinstance(caught.value.__cause__, NonHttpUrlClientError)
    assert str(caught.value) == 'Author image request failed'
    assert signature not in str(caught.value)
    assert caught.value.file is None
    assert previous.read_bytes() == PREVIOUS
    assert previous.stat().st_mtime_ns == timestamp
    _assert_clean(tmp_path)
