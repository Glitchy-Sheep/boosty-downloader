"""Auxiliary images publish complete bytes without claiming occupied paths."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum, auto
from errno import EACCES, ENOSYS, EPERM
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, BinaryIO, Literal

import pytest
from aiohttp import ClientTimeout, NonHttpUrlClientError, TooManyRedirects, web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient
from support.synthetic_post import POST_ID, VIDEO_ID

from boosty_downloader.infrastructure import media_writer, post_images
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadConnectionError,
    DownloadError,
    DownloadIOFailureError,
    DownloadTimeoutError,
    DownloadUnexpectedStatusError,
)
from boosty_downloader.infrastructure.media_workspace import temporary_owned_workspace
from boosty_downloader.infrastructure.post_images import (
    download_locked_teaser,
    download_post_preview,
    has_locked_teaser,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

    from aiohttp import ClientResponse

AUTHOR = 'fixture-author'
POST_FOLDER = f'{AUTHOR}/fixture-post'
PAYLOAD = b'complete image bytes'
MEDIA_ID = f'boosty_video:{VIDEO_ID}'


class _Kind(Enum):
    preview = auto()
    teaser = auto()


@pytest.fixture(params=list(_Kind), ids=lambda kind: kind.name)
def kind(request: pytest.FixtureRequest) -> _Kind:
    value: _Kind = request.param
    return value


@dataclass(frozen=True, slots=True)
class _FileState:
    content: bytes
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _Client:
    session: RetryClient
    url: str

    async def download(self, root: Path, kind: _Kind) -> str:
        match kind:
            case _Kind.preview:
                return await download_post_preview(
                    session=self.session,
                    library_root=root,
                    post_folder=POST_FOLDER,
                    media_id=MEDIA_ID,
                    url=self.url,
                )
            case _Kind.teaser:
                return await download_locked_teaser(
                    session=self.session,
                    library_root=root,
                    author=AUTHOR,
                    post_id=POST_ID,
                    url=self.url,
                )


@asynccontextmanager
async def _client(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    timeout: ClientTimeout | None = None,
) -> AsyncGenerator[_Client, None]:
    app = web.Application()
    app.router.add_get('/image', handler)
    async with (
        TestServer(app) as server,
        RetryClient(
            timeout=timeout, retry_options=ExponentialRetry(attempts=1)
        ) as session,
    ):
        yield _Client(session, str(server.make_url('/image')))


async def _payload(_: web.Request) -> web.Response:
    return web.Response(body=PAYLOAD, content_type='image/png')


def _base(root: Path, kind: _Kind) -> Path:
    match kind:
        case _Kind.preview:
            return root / POST_FOLDER
        case _Kind.teaser:
            return root / AUTHOR


def _relative(kind: _Kind, extension: str = '.png') -> str:
    match kind:
        case _Kind.preview:
            return f'previews/{VIDEO_ID}{extension}'
        case _Kind.teaser:
            return f'.boosty-downloader/teasers/{POST_ID}{extension}'


def _preferred(root: Path, kind: _Kind) -> Path:
    return _base(root, kind) / _relative(kind)


def _existing(root: Path, kind: _Kind, content: bytes = b'keep previous') -> Path:
    path = _preferred(root, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _state(path: Path) -> _FileState:
    return _FileState(path.read_bytes(), path.stat().st_mtime_ns)


def _assert_clean(root: Path) -> None:
    assert not _workspaces(root)


def _workspaces(root: Path) -> list[Path]:
    return list(root.rglob('.boosty-*.part'))


def _assert_empty(root: Path) -> None:
    assert list(root.iterdir()) == []


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except NotImplementedError:
        pytest.skip('Filesystem does not support symlinks')
    except OSError as error:
        if (
            error.errno in {EPERM, EACCES, ENOSYS}
            or getattr(error, 'winerror', None) == 1314
        ):
            pytest.skip('Filesystem does not permit symlinks')
        raise


@pytest.mark.parametrize(
    ('content_type', 'extension'),
    [('image/png', '.png'), ('image/jpeg', '.jpg'), ('application/octet-stream', '')],
)
async def test_identity_and_response_type_choose_the_relative_image_path(
    tmp_path: Path,
    kind: _Kind,
    content_type: str,
    extension: str,
) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=PAYLOAD, content_type=content_type)

    async with _client(handler) as client:
        path = await client.download(tmp_path, kind)

    assert path == _relative(kind, extension)
    assert (_base(tmp_path, kind) / path).read_bytes() == PAYLOAD
    if kind is _Kind.teaser:
        assert not (tmp_path / POST_FOLDER).exists()
    _assert_clean(tmp_path)


@pytest.mark.parametrize('occupied', [b'keep foreign', b''])
async def test_occupied_regular_file_is_preserved_and_gets_a_free_successor(
    tmp_path: Path,
    kind: _Kind,
    occupied: bytes,
) -> None:
    previous = _existing(tmp_path, kind, occupied)
    original = _state(previous)
    foreign = previous.with_name('notes.txt')
    foreign.write_bytes(b'keep notes')
    async with _client(_payload) as client:
        result = await client.download(tmp_path, kind)

    assert _state(previous) == original
    assert foreign.read_bytes() == b'keep notes'
    assert result != _relative(kind)
    assert (_base(tmp_path, kind) / result).read_bytes() == PAYLOAD
    _assert_clean(tmp_path)


@pytest.mark.parametrize(
    ('video_id', 'reserved_paths', 'suffix'),
    [
        (VIDEO_ID, (f'previews/{VIDEO_ID}.png',), 1),
        (VIDEO_ID, (f'PREVIEWS/{VIDEO_ID.upper()}.PNG',), 1),
        ('vidéo', ('previews/vide\u0301o.png',), 1),
        (VIDEO_ID, (f'previews/{VIDEO_ID}.png/original.bin',), 1),
        (VIDEO_ID, (f'PREVIEWS/{VIDEO_ID.upper()}.PNG/original.bin',), 1),
        ('vidéo', ('previews/vide\u0301o.png/original.bin',), 1),
        (VIDEO_ID, (f'previews/{VIDEO_ID}.png', f'previews/{VIDEO_ID} (1).png'), 2),
    ],
)
async def test_missing_reserved_preview_paths_are_preserved(
    tmp_path: Path,
    video_id: str,
    reserved_paths: tuple[str, ...],
    suffix: int,
) -> None:
    async with _client(_payload) as client:
        result = await download_post_preview(
            session=client.session,
            library_root=tmp_path,
            post_folder=POST_FOLDER,
            media_id=f'boosty_video:{video_id}',
            url=client.url,
            reserved_paths=reserved_paths,
        )

    assert result == f'previews/{video_id} ({suffix}).png'
    assert (tmp_path / POST_FOLDER / result).read_bytes() == PAYLOAD
    assert all(not (tmp_path / POST_FOLDER / path).exists() for path in reserved_paths)
    _assert_clean(tmp_path)


@pytest.mark.parametrize('reserved_path', ['previews', 'PREVIEWS'])
async def test_reserved_preview_parent_is_rejected_before_request(
    tmp_path: Path, reserved_path: str
) -> None:
    requests = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal requests
        requests += 1
        return await _payload(request)

    async with _client(handler) as client:
        with pytest.raises(DownloadError):
            await download_post_preview(
                session=client.session,
                library_root=tmp_path,
                post_folder=POST_FOLDER,
                media_id=MEDIA_ID,
                url=client.url,
                reserved_paths=(reserved_path,),
            )

    assert requests == 0
    _assert_empty(tmp_path)


async def test_parent_file_is_rejected_before_request(
    tmp_path: Path, kind: _Kind
) -> None:
    parent_file = _preferred(tmp_path, kind).parent
    parent_file.parent.mkdir(parents=True)
    parent_file.write_bytes(b'keep parent file')
    original = _state(parent_file)
    requests = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal requests
        requests += 1
        return await _payload(request)

    async with _client(handler) as client:
        with pytest.raises(DownloadIOFailureError):
            await client.download(tmp_path, kind)

    assert requests == 0
    assert _state(parent_file) == original
    _assert_clean(tmp_path)


async def test_publication_retry_preserves_reserved_and_newly_occupied_preview_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_available = _preferred(tmp_path, _Kind.preview).with_name(
        f'{VIDEO_ID} (1).png'
    )
    reserved = (
        _relative(_Kind.preview),
        f'previews/{VIDEO_ID} (2).png/original.bin',
    )
    requests = 0

    def occupy_name(file: BinaryIO) -> None:
        file.close()
        first_available.write_bytes(b'occupied during transfer')

    async def handler(request: web.Request) -> web.Response:
        nonlocal requests
        requests += 1
        return await _payload(request)

    monkeypatch.setattr(media_writer, '_close_file', occupy_name)
    async with _client(handler) as client:
        result = await download_post_preview(
            session=client.session,
            library_root=tmp_path,
            post_folder=POST_FOLDER,
            media_id=MEDIA_ID,
            url=client.url,
            reserved_paths=reserved,
        )

    assert requests == 1
    assert result == f'previews/{VIDEO_ID} (3).png'
    assert (tmp_path / POST_FOLDER / result).read_bytes() == PAYLOAD
    assert first_available.read_bytes() == b'occupied during transfer'
    assert all(not (tmp_path / POST_FOLDER / path).exists() for path in reserved)
    _assert_clean(tmp_path)


@pytest.mark.parametrize('target_exists', [False, True])
async def test_final_symlink_is_preserved_without_following_its_target(
    tmp_path: Path,
    kind: _Kind,
    *,
    target_exists: bool,
) -> None:
    root = tmp_path / 'library'
    target = tmp_path / 'outside.png'
    if target_exists:
        target.write_bytes(b'keep outside')
    preferred = _preferred(root, kind)
    preferred.parent.mkdir(parents=True)
    _symlink(preferred, target)

    async with _client(_payload) as client:
        result = await client.download(root, kind)

    assert preferred.is_symlink()
    assert target.exists() is target_exists
    if target_exists:
        assert target.read_bytes() == b'keep outside'
    assert (_base(root, kind) / result).read_bytes() == PAYLOAD
    _assert_clean(root)


async def test_occupied_directory_is_not_replaced(tmp_path: Path, kind: _Kind) -> None:
    preferred = _preferred(tmp_path, kind)
    preferred.mkdir(parents=True)
    (preferred / 'notes').write_bytes(b'keep')
    async with _client(_payload) as client:
        result = await client.download(tmp_path, kind)
    assert (preferred / 'notes').read_bytes() == b'keep'
    assert (_base(tmp_path, kind) / result).read_bytes() == PAYLOAD


@pytest.mark.parametrize('outside', [False, True])
async def test_image_parent_links_are_rejected_before_network_or_writes(
    tmp_path: Path,
    kind: _Kind,
    *,
    outside: bool,
) -> None:
    root = tmp_path / 'library'
    target = tmp_path / 'outside' if outside else root / 'other'
    target.mkdir(parents=True)
    parent = _preferred(root, kind).parent
    parent.parent.mkdir(parents=True, exist_ok=True)
    _symlink(parent, target, directory=True)
    requests = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal requests
        requests += 1
        return await _payload(request)

    async with _client(handler) as client:
        with pytest.raises(DownloadError):
            await client.download(root, kind)

    assert requests == 0
    assert list(target.iterdir()) == []


@pytest.mark.parametrize('status', [403, 404, 500])
async def test_rejected_response_keeps_existing_files(
    tmp_path: Path,
    kind: _Kind,
    status: int,
) -> None:
    previous = _existing(tmp_path, kind)
    original = _state(previous)

    async def handler(_: web.Request) -> web.Response:
        return web.Response(status=status)

    async with _client(handler) as client:
        with pytest.raises(DownloadUnexpectedStatusError) as caught:
            await client.download(tmp_path, kind)

    assert caught.value.status_code == status
    assert _state(previous) == original
    assert list(previous.parent.iterdir()) == [previous]


async def test_truncated_response_leaves_no_new_image(
    tmp_path: Path, kind: _Kind
) -> None:
    previous = _existing(tmp_path, kind)
    original = _state(previous)

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
            await client.download(tmp_path, kind)

    assert _state(previous) == original
    assert list(previous.parent.iterdir()) == [previous]


async def test_empty_response_does_not_publish_an_unusable_image(
    tmp_path: Path, kind: _Kind
) -> None:
    previous = _existing(tmp_path, kind)

    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=b'', content_type='image/png')

    async with _client(handler) as client:
        with pytest.raises(DownloadError, match='Image response is empty'):
            await client.download(tmp_path, kind)

    assert list(previous.parent.iterdir()) == [previous]


async def test_body_timeout_preserves_existing_image(
    tmp_path: Path, kind: _Kind
) -> None:
    previous = _existing(tmp_path, kind)
    release = asyncio.Event()

    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(headers={'Content-Type': 'image/png'})
        await response.prepare(request)
        await response.write(b'partial')
        await release.wait()
        return response

    async with _client(handler, timeout=ClientTimeout(sock_read=0.03)) as client:
        try:
            with pytest.raises(DownloadTimeoutError):
                await client.download(tmp_path, kind)
        finally:
            release.set()

    assert list(previous.parent.iterdir()) == [previous]


@pytest.mark.parametrize('phase', ['write', 'close', 'publish'])
async def test_disk_failures_keep_foreign_bytes_and_clean_temporary_output(
    tmp_path: Path,
    kind: _Kind,
    monkeypatch: pytest.MonkeyPatch,
    phase: Literal['write', 'close', 'publish'],
) -> None:
    previous = _existing(tmp_path, kind)
    original = _state(previous)
    failure = OSError('Test I/O failure')

    async def fail_write(_writer: media_writer.MediaWriter, _data: bytes) -> None:
        raise failure

    def fail_close(file: BinaryIO) -> None:
        file.close()
        raise failure

    def fail_publish(_source: Path, _destination: Path) -> None:
        raise failure

    match phase:
        case 'write':
            monkeypatch.setattr(media_writer.MediaWriter, 'write', fail_write)
        case 'close':
            monkeypatch.setattr(media_writer, '_close_file', fail_close)
        case 'publish':
            monkeypatch.setattr(post_images, 'publish_completed_file', fail_publish)

    async with _client(_payload) as client:
        with pytest.raises(DownloadIOFailureError) as caught:
            await client.download(tmp_path, kind)

    assert caught.value.__cause__ is failure
    assert _state(previous) == original
    assert list(previous.parent.iterdir()) == [previous]


async def test_publication_collision_takes_another_name_without_another_request(
    tmp_path: Path,
    kind: _Kind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preferred = _preferred(tmp_path, kind)
    requests = 0

    def occupy_name(file: BinaryIO) -> None:
        file.close()
        preferred.write_bytes(b'occupied during transfer')

    async def handler(request: web.Request) -> web.Response:
        nonlocal requests
        requests += 1
        return await _payload(request)

    monkeypatch.setattr(media_writer, '_close_file', occupy_name)
    async with _client(handler) as client:
        result = await client.download(tmp_path, kind)

    assert requests == 1
    assert preferred.read_bytes() == b'occupied during transfer'
    assert result != _relative(kind)
    assert (_base(tmp_path, kind) / result).read_bytes() == PAYLOAD
    _assert_clean(tmp_path)


async def test_repeated_cancellation_drains_file_close_before_cleanup(
    tmp_path: Path,
    kind: _Kind,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    previous = _existing(tmp_path, kind)
    original = _state(previous)
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
        task = asyncio.create_task(client.download(tmp_path, kind))
        try:
            await asyncio.wait_for(entered.wait(), timeout=2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert _workspaces(tmp_path)
        finally:
            release.set()
        with pytest.raises(DownloadCancelledError):
            await asyncio.wait_for(task, timeout=2)

    assert all(file.closed for file in files)
    assert _state(previous) == original
    assert list(previous.parent.iterdir()) == [previous]


@pytest.mark.parametrize('failure', [OSError('Close failed'), asyncio.CancelledError()])
async def test_response_close_failure_does_not_publish(
    tmp_path: Path,
    kind: _Kind,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    previous = _existing(tmp_path, kind)
    original_open = post_images.open_download_response

    @asynccontextmanager
    async def fail_close(
        session: RetryClient, url: str
    ) -> AsyncGenerator[ClientResponse, None]:
        async with original_open(session, url) as response:
            yield response
        raise failure

    monkeypatch.setattr(post_images, 'open_download_response', fail_close)
    async with _client(_payload) as client:
        with pytest.raises(DownloadError) as caught:
            await client.download(tmp_path, kind)

    assert caught.value.__cause__ is failure
    assert list(previous.parent.iterdir()) == [previous]


async def test_redirect_loop_does_not_expose_a_signed_url(
    tmp_path: Path, kind: _Kind
) -> None:
    previous = _existing(tmp_path, kind)
    signature = 'fixture-private-signature'

    async def redirect(_: web.Request) -> web.Response:
        return web.Response(
            status=302, headers={'Location': f'/image?token={signature}'}
        )

    async with _client(redirect) as client:
        with pytest.raises(DownloadError) as caught:
            await client.download(tmp_path, kind)

    assert isinstance(caught.value.__cause__, TooManyRedirects)
    assert signature not in str(caught.value)
    assert list(previous.parent.iterdir()) == [previous]


async def test_non_http_image_url_is_a_download_error(
    tmp_path: Path, kind: _Kind
) -> None:
    async with RetryClient(retry_options=ExponentialRetry(attempts=1)) as session:
        with pytest.raises(DownloadError) as caught:
            await _Client(session, 'ftp://example.invalid/image').download(
                tmp_path, kind
            )
    assert isinstance(caught.value.__cause__, NonHttpUrlClientError)
    _assert_empty(tmp_path)


async def test_owned_cleanup_keeps_other_images_and_unknown_workspaces(
    tmp_path: Path, kind: _Kind
) -> None:
    previous = _existing(tmp_path, kind)
    owner = f'preview:{MEDIA_ID}' if kind is _Kind.preview else f'teaser:{POST_ID}'
    with temporary_owned_workspace(previous.parent, owner_id=owner) as workspace:
        (workspace / 'download.tmp').write_bytes(b'interrupted')
        stale = workspace.with_name('.boosty-stopped.part')
        workspace.rename(stale)
    foreign = previous.parent / '.boosty-foreign.part'
    foreign.mkdir()
    (foreign / 'download.tmp').write_bytes(b'keep foreign')
    with temporary_owned_workspace(previous.parent, owner_id='another-image') as other:
        async with _client(_payload) as client:
            await client.download(tmp_path, kind)
        assert other.is_dir()
    assert not stale.exists()
    assert (foreign / 'download.tmp').read_bytes() == b'keep foreign'


@pytest.mark.parametrize('path', [None, '.boosty-downloader/teasers/missing.png'])
def test_missing_saved_teaser_is_a_read_only_miss(
    tmp_path: Path, path: str | None
) -> None:
    assert not has_locked_teaser(tmp_path, AUTHOR, path)
    _assert_empty(tmp_path)


@pytest.mark.parametrize('content', [b'', PAYLOAD])
def test_saved_teaser_requires_nonempty_regular_bytes(
    tmp_path: Path, content: bytes
) -> None:
    image = _existing(tmp_path, _Kind.teaser, content)
    before = _state(image)
    assert has_locked_teaser(tmp_path, AUTHOR, _relative(_Kind.teaser)) is bool(content)
    assert _state(image) == before


def test_saved_teaser_never_follows_a_final_link(tmp_path: Path) -> None:
    image = _preferred(tmp_path, _Kind.teaser)
    image.parent.mkdir(parents=True)
    target = tmp_path / 'other.png'
    target.write_bytes(PAYLOAD)
    _symlink(image, target)
    assert not has_locked_teaser(tmp_path, AUTHOR, _relative(_Kind.teaser))


@pytest.mark.parametrize(
    'path', ['../outside.png', '/outside.png', 'C:/outside.png', 'a\\b']
)
def test_saved_teaser_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match='portable relative file path'):
        has_locked_teaser(tmp_path, AUTHOR, path)
    _assert_empty(tmp_path)


def test_saved_teaser_lookup_does_not_scan_the_author_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _existing(tmp_path, _Kind.teaser)

    def unexpected_scan(_path: Path) -> None:
        pytest.fail('Single teaser lookup must not scan its parent')

    monkeypatch.setattr(Path, 'iterdir', unexpected_scan)
    assert has_locked_teaser(tmp_path, AUTHOR, _relative(_Kind.teaser))


@pytest.mark.parametrize('outside', [False, True])
async def test_publication_rechecks_the_owner_folder_after_streaming(
    tmp_path: Path,
    kind: _Kind,
    monkeypatch: pytest.MonkeyPatch,
    *,
    outside: bool,
) -> None:
    root = tmp_path / 'library'
    previous = _existing(root, kind)
    original = _state(previous)
    owner = _base(root, kind)
    moved = tmp_path / 'moved' if outside else root / 'moved'

    def move_owner(file: BinaryIO) -> None:
        file.close()
        owner.rename(moved)
        _symlink(owner, moved, directory=True)

    monkeypatch.setattr(media_writer, '_close_file', move_owner)
    async with _client(_payload) as client:
        with pytest.raises(DownloadError):
            await client.download(root, kind)

    assert _state(moved / _relative(kind)) == original
    _assert_clean(moved)


@pytest.mark.parametrize(
    'media_id', ['file:other', 'boosty_video:', 'boosty_video:../outside']
)
async def test_invalid_preview_identity_does_not_create_files(
    tmp_path: Path,
    media_id: str,
) -> None:
    async with _client(_payload) as client:
        with pytest.raises(DownloadError) as caught:
            await download_post_preview(
                session=client.session,
                library_root=tmp_path,
                post_folder=POST_FOLDER,
                media_id=media_id,
                url=client.url,
            )
    assert isinstance(caught.value.__cause__, ValueError)
    _assert_empty(tmp_path)


@pytest.mark.parametrize('author', ['', '../outside', 'CON'])
async def test_invalid_teaser_author_does_not_create_files(
    tmp_path: Path, author: str
) -> None:
    async with _client(_payload) as client:
        with pytest.raises(DownloadError) as caught:
            await download_locked_teaser(
                session=client.session,
                library_root=tmp_path,
                author=author,
                post_id=POST_ID,
                url=client.url,
            )
    assert isinstance(caught.value.__cause__, ValueError)
    _assert_empty(tmp_path)
