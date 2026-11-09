from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, field
from errno import EACCES, ENOSYS, EPERM
from typing import TYPE_CHECKING, cast
from urllib.parse import quote

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from yarl import URL

from boosty_downloader.domain.library import SavedPage
from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.viewer.compression import compress_json_responses
from boosty_downloader.viewer.guard import guard_requests, secure_response
from boosty_downloader.viewer.media import serve_media
from boosty_downloader.viewer.media_paths import (
    has_post_folder,
    resolve_author_directory,
    resolve_author_path,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from aiohttp import ClientResponse

    from boosty_downloader.application.ports import LibraryReader

_FILE = b'0123456789abcdefghijklmnopqrstuvwxyz'
_HTML = b'<script>parent.fetch("/api/authors")</script>'


@dataclass
class _Reader:
    loop_thread: int = field(default_factory=threading.get_ident)
    authors: set[str] = field(default_factory=lambda: {'alpha', 'beta'})
    pages: dict[str, SavedPage] = field(default_factory=dict[str, SavedPage])
    calls: list[str] = field(default_factory=list[str])
    proof_error: bool = False

    def has_author(self, author: str) -> bool:
        assert threading.get_ident() != self.loop_thread
        self.calls.append(f'author:{author}')
        return author in self.authors

    def saved_page(self, author: str, path: str) -> SavedPage | None:
        assert threading.get_ident() != self.loop_thread
        self.calls.append(f'page:{author}/{path}')
        if self.proof_error:
            message = '/private/library/post.json is corrupt'
            raise LibraryReadError(message)
        return self.pages.get(f'{author}/{path}')


@dataclass
class _MediaFixture:
    root: Path
    reader: _Reader
    client: TestClient[web.Request, web.Application]


@pytest.fixture
async def media(tmp_path: Path) -> AsyncIterator[_MediaFixture]:
    root = tmp_path / 'library'
    for name in ('alpha', 'beta', '.boosty-downloader', '.ssh', 'unlisted'):
        (root / name).mkdir(parents=True)
    (root / 'alpha/post/files').mkdir(parents=True)
    (root / 'alpha/post/movie.mp4').write_bytes(_FILE)
    reader = _Reader()

    async def handle(request: web.Request) -> web.StreamResponse:
        return await serve_media(
            request, reader=cast('LibraryReader', reader), library_root=root
        )

    app = web.Application(middlewares=[compress_json_responses, guard_requests])
    app.on_response_prepare.append(secure_response)
    app.router.add_get('/media/{author}/{path:.+}', handle)
    async with TestClient(TestServer(app), auto_decompress=False) as client:
        yield _MediaFixture(root, reader, client)


def _assert_boundary(response: ClientResponse) -> None:
    headers = response.headers
    assert headers['X-Content-Type-Options'] == 'nosniff'
    assert headers['Cross-Origin-Resource-Policy'] == 'same-origin'
    assert headers['Referrer-Policy'] == 'no-referrer'


def _assert_attachment(response: ClientResponse) -> None:
    headers = response.headers
    _assert_boundary(response)
    assert headers['Content-Type'] == 'application/octet-stream'
    assert headers['Content-Disposition'] == 'attachment'
    assert "sandbox; default-src 'none'" in headers['Content-Security-Policy']
    assert 'allow-scripts' not in headers['Content-Security-Policy']
    assert 'X-Frame-Options' not in headers


@pytest.mark.parametrize('encoding', ['', 'gzip, br', 'br', '*'])
async def test_exact_media_ignores_compressed_siblings(
    media: _MediaFixture, encoding: str
):
    path = media.root / 'alpha/post/movie.mp4'
    path.with_name(path.name + '.gz').write_bytes(b'wrong gzip')
    path.with_name(path.name + '.br').write_bytes(b'wrong brotli')
    response = await media.client.get(
        '/media/alpha/post/movie.mp4', headers={'Accept-Encoding': encoding}
    )
    assert response.status == 200
    assert await response.read() == _FILE
    assert 'Content-Encoding' not in response.headers
    assert response.headers['Content-Type'] == 'video/mp4'
    _assert_boundary(response)
    assert media.reader.calls == ['author:alpha']


async def test_range_returns_only_the_requested_bytes(media: _MediaFixture):
    response = await media.client.get(
        '/media/alpha/post/movie.mp4', headers={'Range': 'bytes=3-8'}
    )
    assert response.status == 206
    assert await response.read() == _FILE[3:9]
    assert response.headers['Content-Range'] == f'bytes 3-8/{len(_FILE)}'
    assert response.headers['Accept-Ranges'] == 'bytes'
    _assert_boundary(response)
    invalid = await media.client.get(
        '/media/alpha/post/movie.mp4', headers={'Range': 'bytes=999-1000'}
    )
    assert invalid.status == 416
    assert invalid.headers['Content-Range'] == f'bytes */{len(_FILE)}'
    _assert_boundary(invalid)


async def test_head_and_conditional_media_keep_policy(media: _MediaFixture):
    first = await media.client.get('/media/alpha/post/movie.mp4')
    await first.read()
    head = await media.client.head('/media/alpha/post/movie.mp4')
    assert head.status == 200
    assert await head.read() == b''
    assert head.headers['Content-Length'] == str(len(_FILE))
    _assert_boundary(head)
    cached = await media.client.get(
        '/media/alpha/post/movie.mp4', headers={'If-None-Match': first.headers['ETag']}
    )
    assert cached.status == 304
    assert await cached.read() == b''
    _assert_boundary(cached)


@pytest.mark.parametrize(
    'relative',
    [
        'page.html',
        'page.htm',
        'page.xhtml',
        'image.svg',
        'page.xml',
        'page.mhtml',
        'file.bin',
        'script.js',
        'thing.unknown',
        'page.html::$DATA',
    ],
)
async def test_active_and_unknown_files_are_inert_downloads(
    media: _MediaFixture, relative: str
):
    if os.name == 'nt' and ':' in relative:
        pytest.skip('Native alternate stream aliases are covered separately')
    (media.root / 'alpha/post/files' / relative).write_bytes(_HTML)
    response = await media.client.get('/media/alpha/post/files/' + quote(relative))
    assert response.status == 200
    assert await response.read() == _HTML
    _assert_attachment(response)


@pytest.mark.parametrize(
    ('name', 'content_type'),
    [
        ('page.pdf', 'application/pdf'),
        ('Заметки.txt', 'text/plain; charset=utf-8'),
        ('photo.PNG', 'image/png'),
    ],
)
async def test_safe_types_are_explicit(
    media: _MediaFixture, name: str, content_type: str
):
    payload = 'Привет, мир'.encode()
    (media.root / 'alpha/post/files' / name).write_bytes(payload)
    response = await media.client.get('/media/alpha/post/files/' + quote(name))
    assert response.status == 200
    assert response.headers['Content-Type'] == content_type
    assert 'Content-Disposition' not in response.headers
    assert await response.read() == payload
    _assert_boundary(response)


@pytest.mark.parametrize(
    'route',
    [
        '/media/.boosty-downloader/index.db',
        '/media/.ssh/id_rsa',
        '/media/unlisted/config.yaml',
        '/media/unknown/config.yaml',
        '/media/%2e%2e/config.yaml',
        '/media/alpha/%2e%2e/config.yaml',
        '/media/alpha/../config.yaml',
        '/media/alpha/post/..%5cconfig.yaml',
        '/media/alpha/%2fetc/passwd',
        '/media/alpha/C%3a/config.yaml',
        '/media/alpha/post/C%3aconfig.yaml',
        '/media/alpha/%5c%5cserver/share/file',
        '/media/alpha/post/%00secret',
        '/media/alpha/post/missing',
        '/media/alpha/post/files',
        '/media/alpha/post//movie.mp4',
    ],
)
async def test_private_invalid_and_non_file_paths_are_404(
    media: _MediaFixture, route: str
):
    (media.root / '.boosty-downloader/index.db').write_bytes(b'private')
    (media.root / '.ssh/id_rsa').write_bytes(b'private')
    (media.root / 'unlisted/config.yaml').write_bytes(b'private')
    response = await media.client.get(URL(route, encoded=True))
    assert response.status == 404
    assert b'private' not in await response.read()
    assert not any(call.startswith('page:') for call in media.reader.calls)


async def test_route_is_decoded_exactly_once(media: _MediaFixture):
    directory = media.root / 'alpha/%2e%2e'
    directory.mkdir()
    (directory / 'literal.txt').write_bytes(b'percent is a filename')
    response = await media.client.get(
        URL('/media/alpha/%252e%252e/literal.txt', encoded=True)
    )
    assert response.status == 200
    assert await response.read() == b'percent is a filename'


@pytest.mark.parametrize('target_kind', ['outside', 'other_author', 'service', 'loop'])
async def test_escaping_or_looped_links_are_404(media: _MediaFixture, target_kind: str):
    link = media.root / 'alpha/post/linked.png'
    targets = {
        'outside': media.root.parent / 'private.png',
        'other_author': media.root / 'beta/private.png',
        'service': media.root / '.boosty-downloader/private.png',
        'loop': link,
    }
    target = targets[target_kind]
    if target_kind != 'loop':
        target.write_bytes(b'private')
    _symlink(link, target)
    response = await media.client.get('/media/alpha/post/linked.png')
    assert response.status == 404
    assert b'private' not in await response.read()


async def test_contained_image_link_serves_the_image(media: _MediaFixture):
    image = media.root / 'alpha/post/files/photo.png'
    image.write_bytes(_FILE)
    _symlink(media.root / 'alpha/post/linked.png', image)
    response = await media.client.get('/media/alpha/post/linked.png')
    assert response.status == 200
    assert response.headers['Content-Type'] == 'image/png'
    assert await response.read() == _FILE
    assert media.reader.calls == ['author:alpha']


@pytest.mark.parametrize('generated', [False, True])
async def test_picture_named_link_to_html_downloads(
    media: _MediaFixture, *, generated: bool
):
    target = media.root / 'alpha/post/post.html'
    target.write_bytes(_HTML)
    if generated:
        media.reader.pages['alpha/post/post.html'] = SavedPage(
            'alpha/post', 'alpha/post/post.html'
        )
    _symlink(media.root / 'alpha/post/pic.png', target)
    response = await media.client.get('/media/alpha/post/pic.png')
    assert response.status == 200
    assert await response.read() == _HTML
    _assert_attachment(response)
    assert media.reader.calls == ['author:alpha']


async def test_confirmed_saved_page_gets_an_opaque_scripted_sandbox(
    media: _MediaFixture,
):
    (media.root / 'alpha/post/post.html').write_bytes(_HTML)
    media.reader.pages['alpha/post/post.html'] = SavedPage(
        'alpha/post', 'alpha/post/post.html'
    )
    response = await media.client.get('/media/alpha/post/post.html')
    assert response.status == 200
    assert await response.read() == _HTML
    assert response.headers['Content-Type'] == 'text/html; charset=utf-8'
    policy = response.headers['Content-Security-Policy']
    assert 'sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox' in policy
    assert 'allow-same-origin' not in policy
    assert "frame-ancestors 'self'" in policy
    assert 'Content-Disposition' not in response.headers
    assert 'X-Frame-Options' not in response.headers
    _assert_boundary(response)


@pytest.mark.parametrize(
    'proof', ['absent', 'different_path', 'different_folder', 'corrupt']
)
async def test_unproven_pages_download_without_exposing_record_errors(
    media: _MediaFixture, proof: str
):
    (media.root / 'alpha/post/post.html').write_bytes(_HTML)
    pages = {
        'different_path': SavedPage('alpha/other', 'alpha/other/post.html'),
        'different_folder': SavedPage('alpha/other', 'alpha/post/post.html'),
    }
    if proof in pages:
        media.reader.pages['alpha/post/post.html'] = pages[proof]
    media.reader.proof_error = proof == 'corrupt'
    response = await media.client.get('/media/alpha/post/post.html')
    assert response.status == 200
    assert await response.read() == _HTML
    _assert_attachment(response)


async def test_an_alias_to_a_confirmed_page_does_not_gain_its_policy(
    media: _MediaFixture,
):
    target = media.root / 'alpha/post/post.html'
    target.write_bytes(_HTML)
    media.reader.pages['alpha/alias/post.html'] = SavedPage(
        'alpha/post', 'alpha/post/post.html'
    )
    (media.root / 'alpha/alias').mkdir()
    _symlink(media.root / 'alpha/alias/post.html', target)
    response = await media.client.get('/media/alpha/alias/post.html')
    assert response.status == 200
    _assert_attachment(response)


@pytest.mark.parametrize('target_name', ['.boosty-downloader', 'beta'])
async def test_author_alias_cannot_retarget_the_boundary(
    media: _MediaFixture, target_name: str
):
    (media.root / target_name / 'private.txt').write_bytes(b'private')
    _symlink(media.root / 'alias', media.root / target_name, directory=True)
    media.reader.authors.add('alias')
    response = await media.client.get('/media/alias/private.txt')
    assert response.status == 404
    assert b'private' not in await response.read()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX named pipe')
async def test_special_files_are_rejected_without_opening(media: _MediaFixture):
    os.mkfifo(media.root / 'alpha/post/pipe')
    response = await asyncio.wait_for(
        media.client.get('/media/alpha/post/pipe'), timeout=2
    )
    assert response.status == 404


@pytest.mark.skipif(os.name != 'nt', reason='Windows filename aliases')
@pytest.mark.parametrize('name', ['page.html', 'post.html'])
@pytest.mark.parametrize('alias_suffix', ['.', ' ', '::$DATA'])
async def test_windows_html_aliases_download(
    media: _MediaFixture, name: str, alias_suffix: str
):
    (media.root / 'alpha/post' / name).write_bytes(_HTML)
    media.reader.pages['alpha/post/post.html'] = SavedPage(
        'alpha/post', 'alpha/post/post.html'
    )
    alias = name + alias_suffix
    response = await media.client.get('/media/alpha/post/' + quote(alias))
    assert response.status == 200
    assert await response.read() == _HTML
    _assert_attachment(response)


def test_post_folder_checks_exact_author_and_containment(tmp_path: Path):
    (tmp_path / 'alpha/post').mkdir(parents=True)
    (tmp_path / 'beta/post').mkdir(parents=True)
    assert has_post_folder(tmp_path, 'alpha', 'alpha/post')
    assert not has_post_folder(tmp_path, 'alpha', 'beta/post')
    assert not has_post_folder(tmp_path, 'alpha', 'alpha/../beta/post')
    assert not has_post_folder(tmp_path, 'alpha', 'alpha/missing')
    assert not has_post_folder(tmp_path, 'alpha', 'alpha')
    assert resolve_author_directory(tmp_path, '.boosty-downloader') is None
    assert resolve_author_path(tmp_path, 'alpha', 'C:other') is None
    assert resolve_author_path(tmp_path, 'alpha', 'post/./file') is None


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
