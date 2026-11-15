from __future__ import annotations

import gzip
from errno import EACCES, ENOSYS, EPERM
from typing import TYPE_CHECKING

import pytest
from aiohttp.test_utils import TestClient, TestServer
from yarl import URL

from boosty_downloader.viewer.app import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from aiohttp import web

_SCRIPT = b'console.log("viewer");\n'
# Brotli bytes produced from _SCRIPT with node:zlib.brotliCompressSync.
_BROTLI_SCRIPT = bytes.fromhex('0b0b80636f6e736f6c652e6c6f67282276696577657222293b0a03')


@pytest.fixture
def static_root(tmp_path: Path) -> Path:
    root = tmp_path / 'app'
    (root / 'assets').mkdir(parents=True)
    (root / 'index.html').write_text(
        '<html><body>Viewer shell</body></html>', encoding='utf-8'
    )
    (root / 'assets/app-abc123.js').write_bytes(_SCRIPT)
    (root / 'assets/app-abc123.js.gz').write_bytes(gzip.compress(_SCRIPT, mtime=0))
    (root / 'assets/app-abc123.js.br').write_bytes(_BROTLI_SCRIPT)
    return root


@pytest.fixture
async def static_client(
    static_root: Path,
) -> AsyncIterator[TestClient[web.Request, web.Application]]:
    app = create_app(reader=None, static_directory=static_root)
    async with TestClient(
        TestServer(app), auto_decompress=False, headers={'Accept-Encoding': ''}
    ) as client:
        yield client


@pytest.mark.parametrize('path', ['/', '/index.html', '/a/creator/p/saved-post'])
async def test_client_routes_get_uncached_index(
    static_client: TestClient[web.Request, web.Application], path: str
):
    response = await static_client.get(path, headers={'Accept-Encoding': ''})
    assert response.status == 200
    assert 'Viewer shell' in await response.text()
    assert response.headers['Cache-Control'] == 'no-cache'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert "script-src 'self'" in response.headers['Content-Security-Policy']


@pytest.mark.parametrize(
    ('header', 'encoding', 'body'),
    [
        ('br, gzip', 'br', _BROTLI_SCRIPT),
        ('br;q=0, gzip', 'gzip', gzip.compress(_SCRIPT, mtime=0)),
        ('br;q=0.4, gzip;q=0.8', 'gzip', gzip.compress(_SCRIPT, mtime=0)),
        ('br;q=0, gzip;q=0', None, _SCRIPT),
        ('x-gzip', None, _SCRIPT),
        ('', None, _SCRIPT),
    ],
)
async def test_asset_negotiation_uses_the_selected_file(
    static_client: TestClient[web.Request, web.Application],
    header: str,
    encoding: str | None,
    body: bytes,
):
    response = await static_client.get(
        '/assets/app-abc123.js', headers={'Accept-Encoding': header}
    )
    assert response.status == 200
    assert response.headers.get('Content-Encoding') == encoding
    assert await response.read() == body
    assert 'javascript' in response.headers['Content-Type']
    assert response.headers['Vary'] == 'Accept-Encoding'
    assert response.headers['Cache-Control'] == 'public, max-age=31536000, immutable'


async def test_no_acceptable_static_encoding_returns_406(
    static_client: TestClient[web.Request, web.Application],
):
    response = await static_client.get(
        '/assets/app-abc123.js', headers={'Accept-Encoding': '*;q=0'}
    )
    assert response.status == 406
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


@pytest.mark.parametrize(
    'path',
    [
        '/assets',
        '/assets/missing.js',
        '/api',
        '/api/authors',
        '/media',
        '/media/private/config.yaml',
    ],
)
async def test_reserved_and_missing_asset_paths_are_not_the_spa(
    static_client: TestClient[web.Request, web.Application], path: str
):
    response = await static_client.get(path)
    assert response.status == 404
    assert 'Viewer shell' not in await response.text()
    assert response.headers['X-Frame-Options'] == 'DENY'


@pytest.mark.parametrize(
    'path',
    [
        '/assets/%2e%2e/%2e%2e/secret',
        '/assets/..%5csecret',
        '/assets/file.js%3a%3a$DATA',
    ],
)
async def test_escaping_and_nonportable_paths_are_not_served(
    static_client: TestClient[web.Request, web.Application], path: str
):
    response = await static_client.get(URL(path, encoded=True))
    assert response.status == 404


async def test_asset_link_cannot_leave_static_directory(
    static_client: TestClient[web.Request, web.Application],
    static_root: Path,
    tmp_path: Path,
):
    secret = tmp_path / 'secret.js'
    secret.write_text('secret', encoding='utf-8')
    _symlink(static_root / 'assets/linked.js', secret)
    response = await static_client.get('/assets/linked.js')
    assert response.status == 404
    assert 'secret' not in await response.text()


async def test_compressed_symlink_is_not_selected(
    static_client: TestClient[web.Request, web.Application],
    static_root: Path,
    tmp_path: Path,
):
    sidecar = static_root / 'assets/app-abc123.js.br'
    sidecar.unlink()
    external = tmp_path / 'external.br'
    external.write_bytes(b'external')
    _symlink(sidecar, external)
    response = await static_client.get(
        '/assets/app-abc123.js', headers={'Accept-Encoding': 'br'}
    )
    assert response.status == 200
    assert 'Content-Encoding' not in response.headers
    assert await response.read() == _SCRIPT


async def test_head_and_conditional_responses_keep_headers(
    static_client: TestClient[web.Request, web.Application],
):
    first = await static_client.get(
        '/assets/app-abc123.js', headers={'Accept-Encoding': ''}
    )
    etag = first.headers['ETag']
    await first.read()
    response = await static_client.get(
        '/assets/app-abc123.js', headers={'Accept-Encoding': '', 'If-None-Match': etag}
    )
    assert response.status == 304
    assert response.headers['X-Frame-Options'] == 'DENY'
    head = await static_client.head(
        '/assets/app-abc123.js', headers={'Accept-Encoding': ''}
    )
    assert head.status == 200
    assert await head.read() == b''
    assert head.headers['Cache-Control'].endswith('immutable')


async def test_missing_build_explains_how_to_build(tmp_path: Path):
    app = create_app(reader=None, static_directory=tmp_path / 'missing')
    async with TestClient(TestServer(app)) as client:
        response = await client.get('/')
        assert response.status == 503
        assert 'task ui:build' in await response.text()
        assert response.headers['Cache-Control'] == 'no-cache'


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except NotImplementedError:
        pytest.skip('Filesystem does not support symlinks')
    except OSError as error:
        if (
            error.errno in {EPERM, EACCES, ENOSYS}
            or getattr(error, 'winerror', None) == 1314
        ):
            pytest.skip('Filesystem does not permit symlinks')
        raise
