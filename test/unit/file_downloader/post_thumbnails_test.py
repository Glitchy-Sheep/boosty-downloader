"""Bounded thumbnails preserve signed URLs, owned paths, and existing bytes."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from errno import EACCES, ENOSYS, EPERM
from gzip import compress
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient
from support.raster_images import png_bytes, png_chunk

from boosty_downloader.infrastructure import media_writer
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadError,
)
from boosty_downloader.infrastructure.post_thumbnails import (
    MAX_THUMBNAIL_BYTES,
    build_thumbnail_url,
    download_post_thumbnail,
    download_teaser_thumbnail,
    has_thumbnail,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

AUTHOR = 'author'
POST_ID = 'post-one'
MEDIA_ID = 'image:one'
DIRECTORY = '.boosty-downloader/thumbs'


@dataclass(frozen=True, slots=True)
class _Client:
    session: RetryClient
    url: str

    async def download(
        self, root: Path, post_id: str = POST_ID, media_id: str = MEDIA_ID
    ) -> str:
        return await download_post_thumbnail(
            session=self.session,
            library_root=root,
            author=AUTHOR,
            post_id=post_id,
            media_id=media_id,
            url=self.url,
        )


@asynccontextmanager
async def _client(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> AsyncGenerator[_Client, None]:
    app = web.Application()
    app.router.add_get('/image', handler)
    async with (
        TestServer(app) as server,
        RetryClient(retry_options=ExponentialRetry(attempts=1)) as session,
    ):
        yield _Client(session, str(server.make_url('/image')))


async def _png(_: web.Request) -> web.Response:
    return web.Response(body=png_bytes(), content_type='image/png')


def _assert_clean(root: Path) -> None:
    assert not list(root.rglob('*.part'))
    assert not list(root.rglob('*.tmp'))


def _assert_no_images(root: Path) -> None:
    assert not list(root.rglob('*.png'))
    _assert_clean(root)


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
    ('url', 'expected'),
    [
        ('https://image.invalid/a', 'https://image.invalid/a?mw=480'),
        (
            'https://image.invalid/a?mw=80&token=a%2fb%2Bc+z&&sig=%25#x',
            'https://image.invalid/a?token=a%2fb%2Bc+z&&sig=%25&mw=480#x',
        ),
        (
            'https://image.invalid/a?mh=10&croped=0&mw=80&mw=90&%6dw=7',
            'https://image.invalid/a?mw=480',
        ),
        (
            'http://image.invalid/a?odd&empty=&XMW=1',
            'http://image.invalid/a?odd&empty=&XMW=1&mw=480',
        ),
    ],
)
def test_resize_keeps_unrelated_query_bytes(url: str, expected: str) -> None:
    assert build_thumbnail_url(url) == expected


@pytest.mark.parametrize(
    'url', ['file:///tmp/a', 'ftp://image.invalid/a', '//image.invalid/a', 'https:///a']
)
def test_only_http_urls_are_accepted(url: str) -> None:
    with pytest.raises(ValueError, match='HTTP'):
        build_thumbnail_url(url)


async def test_http_request_preserves_signed_escape_bytes(tmp_path: Path) -> None:
    received: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        received.append(request.raw_path)
        return await _png(request)

    async with _client(handler) as client:
        signed = _Client(client.session, f'{client.url}?sig=a%2fb%2Bc+z&&empty=&mh=9')
        path = await signed.download(tmp_path)
    assert received == ['/image?sig=a%2fb%2Bc+z&&empty=&mw=480']
    assert (tmp_path / AUTHOR / path).read_bytes() == png_bytes()
    assert has_thumbnail(tmp_path, AUTHOR, path)
    _assert_clean(tmp_path)


async def test_full_post_media_and_teaser_identities_are_distinct(
    tmp_path: Path,
) -> None:
    async with _client(_png) as client:
        paths = {
            await client.download(tmp_path, 'post-one', 'image:same'),
            await client.download(tmp_path, 'post-two', 'image:same'),
            await client.download(tmp_path, 'post-one', 'image:other'),
            await client.download(tmp_path, 'post/one', 'image:\\odd:*'),
            await download_teaser_thumbnail(
                session=client.session,
                library_root=tmp_path,
                author=AUTHOR,
                post_id='post-one',
                url=client.url,
            ),
        }
    assert len(paths) == 5
    for path in paths:
        assert Path(path).parent.as_posix() == DIRECTORY
        assert len(Path(path).stem) == 64
        assert all(character in '0123456789abcdef' for character in Path(path).stem)


@pytest.mark.parametrize('mime', ['image/png', 'application/octet-stream', None])
async def test_header_determines_extension(tmp_path: Path, mime: str | None) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(
            body=png_bytes(), headers={'Content-Type': mime} if mime else {}
        )

    async with _client(handler) as client:
        path = await client.download(tmp_path)
    assert path.endswith('.png')


@pytest.mark.parametrize('mime', ['image/jpeg', 'text/html', 'image/svg+xml'])
async def test_contradictory_mime_is_rejected(tmp_path: Path, mime: str) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=png_bytes(), content_type=mime)

    async with _client(handler) as client:
        with pytest.raises(DownloadError, match='content type'):
            await client.download(tmp_path)
    _assert_no_images(tmp_path)


@pytest.mark.parametrize(
    'data',
    [
        b'',
        b'<html>bad</html>',
        b'<svg/>',
        png_bytes()[:25],
        png_bytes(0, 2),
        png_bytes(2, 0),
        png_bytes(481, 1),
    ],
)
async def test_invalid_or_oversized_raster_is_not_published(
    tmp_path: Path, data: bytes
) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=data, content_type='image/png')

    async with _client(handler) as client:
        with pytest.raises(DownloadError):
            await client.download(tmp_path)
    _assert_no_images(tmp_path)


async def test_exact_requested_width_is_accepted(tmp_path: Path) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=png_bytes(480, 900), content_type='image/png')

    async with _client(handler) as client:
        path = await client.download(tmp_path)
    assert has_thumbnail(tmp_path, AUTHOR, path)


@pytest.mark.parametrize('declared', [False, True])
async def test_body_limit_rejects_before_excess_bytes_are_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, declared: bool
) -> None:
    written = 0
    original = media_writer.MediaWriter.write

    async def observe(writer: media_writer.MediaWriter, data: bytes) -> None:
        nonlocal written
        written += len(data)
        await original(writer, data)

    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse(
            headers={'Content-Length': str(MAX_THUMBNAIL_BYTES + 1)} if declared else {}
        )
        await response.prepare(request)
        await response.write(b'x' * (MAX_THUMBNAIL_BYTES + 1))
        return response

    monkeypatch.setattr(media_writer.MediaWriter, 'write', observe)
    async with _client(handler) as client:
        with pytest.raises(DownloadError, match='byte limit'):
            await client.download(tmp_path)
    assert written <= MAX_THUMBNAIL_BYTES
    if declared:
        assert written == 0
    _assert_clean(tmp_path)


async def test_occupied_image_is_preserved_without_another_request(
    tmp_path: Path,
) -> None:
    async with _client(_png) as client:
        first = await client.download(tmp_path)
        (tmp_path / AUTHOR / first).write_bytes(b'keep')
        second = await client.download(tmp_path)
    assert first != second
    assert (tmp_path / AUTHOR / first).read_bytes() == b'keep'
    assert (tmp_path / AUTHOR / second).read_bytes() == png_bytes()


async def test_publication_retries_a_collision_created_during_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with _client(_png) as client:
        first = await client.download(tmp_path)
        target = tmp_path / AUTHOR / first
        target.unlink()

        def occupy(file: BinaryIO) -> None:
            file.close()
            target.write_bytes(b'keep')

        monkeypatch.setattr(media_writer, '_close_file', occupy)
        second = await client.download(tmp_path)
    assert first != second
    assert target.read_bytes() == b'keep'
    _assert_clean(tmp_path)


@pytest.mark.parametrize(
    'parent', ['author', 'author/.boosty-downloader', f'author/{DIRECTORY}']
)
async def test_parent_symlinks_are_rejected_before_request(
    tmp_path: Path, parent: str
) -> None:
    root = tmp_path / 'library'
    target = root / 'other'
    target.mkdir(parents=True)
    alias = root / parent
    alias.parent.mkdir(parents=True, exist_ok=True)
    _symlink(alias, target, directory=True)
    requests = 0

    async def handler(request: web.Request) -> web.Response:
        nonlocal requests
        requests += 1
        return await _png(request)

    async with _client(handler) as client:
        with pytest.raises(DownloadError):
            await client.download(root)
    assert requests == 0
    assert list(target.iterdir()) == []


async def test_final_symlink_is_preserved(tmp_path: Path) -> None:
    async with _client(_png) as client:
        first = await client.download(tmp_path)
        path = tmp_path / AUTHOR / first
        path.unlink()
        outside = tmp_path / 'outside.png'
        outside.write_bytes(b'keep')
        _symlink(path, outside)
        assert not has_thumbnail(tmp_path, AUTHOR, first)
        second = await client.download(tmp_path)
    assert path.is_symlink()
    assert first != second
    assert outside.read_bytes() == b'keep'


async def test_cancellation_cleans_owned_workspace(tmp_path: Path) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def handler(request: web.Request) -> web.StreamResponse:
        response = web.StreamResponse()
        await response.prepare(request)
        await response.write(b'partial')
        entered.set()
        await release.wait()
        return response

    async with _client(handler) as client:
        task = asyncio.create_task(client.download(tmp_path))
        await asyncio.wait_for(entered.wait(), timeout=2)
        task.cancel()
        try:
            with pytest.raises(DownloadCancelledError):
                await task
        finally:
            release.set()
    _assert_clean(tmp_path)


@pytest.mark.parametrize('path', [None, f'{DIRECTORY}/missing.png'])
def test_lookup_is_read_only(
    tmp_path: Path, path: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_scan(_: Path) -> None:
        pytest.fail('Thumbnail lookup must not scan')

    with monkeypatch.context() as context:
        context.setattr(Path, 'iterdir', no_scan)
        assert not has_thumbnail(tmp_path, AUTHOR, path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    'path',
    [
        '../outside.png',
        f'{DIRECTORY}/nested/x.png',
        '.boosty-downloader/teasers/x.png',
        '/outside.png',
    ],
)
def test_lookup_rejects_outside_thumbnail_paths(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError, match='Thumbnail must be directly under'):
        has_thumbnail(tmp_path, AUTHOR, path)


def test_empty_saved_thumbnail_is_a_miss(tmp_path: Path) -> None:
    path = f'{DIRECTORY}/empty.png'
    target = tmp_path / AUTHOR / path
    target.parent.mkdir(parents=True)
    target.touch()
    assert not has_thumbnail(tmp_path, AUTHOR, path)


async def test_exact_byte_limit_is_accepted(tmp_path: Path) -> None:
    original = png_bytes()
    padding = b'padding\0' + b'x' * (MAX_THUMBNAIL_BYTES - len(original) - 20)
    data = original[:-12] + png_chunk(b'tEXt', padding) + original[-12:]
    assert len(data) == MAX_THUMBNAIL_BYTES

    async def handler(_: web.Request) -> web.Response:
        return web.Response(body=data, content_type='image/png')

    async with _client(handler) as client:
        path = await client.download(tmp_path)
    assert (tmp_path / AUTHOR / path).stat().st_size == MAX_THUMBNAIL_BYTES


async def test_compressed_body_cannot_bypass_the_byte_limit(tmp_path: Path) -> None:
    async def handler(_: web.Request) -> web.Response:
        return web.Response(
            body=compress(b'x' * (MAX_THUMBNAIL_BYTES + 1)),
            headers={'Content-Encoding': 'gzip'},
        )

    async with _client(handler) as client:
        with pytest.raises(DownloadError, match='byte limit'):
            await client.download(tmp_path)
    _assert_no_images(tmp_path)


async def test_failed_refresh_preserves_previous_image(tmp_path: Path) -> None:
    async with _client(_png) as client:
        path = await client.download(tmp_path)
    previous = tmp_path / AUTHOR / path
    modified = previous.stat().st_mtime_ns

    async def broken(_: web.Request) -> web.Response:
        return web.Response(body=b'<html>expired</html>')

    async with _client(broken) as client:
        with pytest.raises(DownloadError, match='raster header'):
            await client.download(tmp_path)
    assert previous.read_bytes() == png_bytes()
    assert previous.stat().st_mtime_ns == modified
    _assert_clean(tmp_path)


async def test_owner_change_during_transfer_prevents_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    author = tmp_path / AUTHOR
    moved = tmp_path / 'moved'

    def move_author(file: BinaryIO) -> None:
        file.close()
        author.rename(moved)
        _symlink(author, moved, directory=True)

    monkeypatch.setattr(media_writer, '_close_file', move_author)
    async with _client(_png) as client:
        with pytest.raises(DownloadError):
            await client.download(tmp_path)
    _assert_no_images(moved)
