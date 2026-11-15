from __future__ import annotations

import gzip
import json
import zlib
from typing import TYPE_CHECKING

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from boosty_downloader.viewer.compression import (
    ContentEncoding,
    compress_json_responses,
    select_encoding,
)
from boosty_downloader.viewer.guard import guard_requests, secure_response

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_ENCODINGS = (
    ContentEncoding.brotli,
    ContentEncoding.gzip,
    ContentEncoding.deflate,
    ContentEncoding.identity,
)


@pytest.mark.parametrize(
    ('header', 'expected'),
    [
        ('', ContentEncoding.identity),
        ('gzip, br', ContentEncoding.brotli),
        ('gzip;q=0.8, br;q=0.4', ContentEncoding.gzip),
        ('br;q=0, gzip', ContentEncoding.gzip),
        ('gzip;q=0', ContentEncoding.identity),
        ('x-gzip', ContentEncoding.identity),
        ('BR;Q=1.0', ContentEncoding.brotli),
        ('*;q=0.5, br;q=0', ContentEncoding.gzip),
        ('*;q=0', None),
        ('*;q=0, identity;q=0.5', ContentEncoding.identity),
        ('identity;q=1, gzip;q=0.8', ContentEncoding.identity),
        ('identity;q=0, gzip;q=0', None),
        ('gzip;q=0, gzip;q=1', ContentEncoding.identity),
        ('gzip;q=nan', ContentEncoding.identity),
        ('gzip;q=2', ContentEncoding.identity),
        ('gzip;q=-1', ContentEncoding.identity),
        ('gzip;q=.5', ContentEncoding.identity),
        ('gzip;q=0.0001', ContentEncoding.identity),
        ('gzip;q=1;level=9', ContentEncoding.identity),
        ('unknown, compress', ContentEncoding.identity),
    ],
)
def test_encoding_preferences(header: str, expected: ContentEncoding | None):
    assert select_encoding(header, _ENCODINGS) == expected


def test_missing_preferred_representation_uses_the_next_available():
    assert select_encoding('br, gzip', _ENCODINGS[1:]) == ContentEncoding.gzip


async def _json(request: web.Request) -> web.Response:
    del request
    return web.json_response({'message': 'sample library ' * 100})


@pytest.fixture
async def json_client() -> AsyncIterator[TestClient[web.Request, web.Application]]:
    app = web.Application(middlewares=[compress_json_responses, guard_requests])
    app.on_response_prepare.append(secure_response)
    app.router.add_get('/json', _json)
    async with TestClient(TestServer(app), auto_decompress=False) as client:
        yield client


@pytest.mark.parametrize(
    ('header', 'encoding'),
    [
        ('gzip', 'gzip'),
        ('gzip;q=0, deflate;q=0.5', 'deflate'),
        ('br;q=0, gzip;q=1', 'gzip'),
        ('gzip;q=0, deflate;q=0', None),
        ('', None),
    ],
)
async def test_json_compression_respects_quality(
    json_client: TestClient[web.Request, web.Application],
    header: str,
    encoding: str | None,
):
    response = await json_client.get('/json', headers={'Accept-Encoding': header})
    assert response.status == 200
    assert response.headers.get('Content-Encoding') == encoding
    body = await response.read()
    if encoding == 'gzip':
        body = gzip.decompress(body)
    elif encoding == 'deflate':
        body = zlib.decompress(body)
    assert json.loads(body) == {'message': 'sample library ' * 100}
    assert 'Accept-Encoding' in response.headers['Vary']


async def test_unacceptable_json_encoding_returns_406_with_security_headers(
    json_client: TestClient[web.Request, web.Application],
):
    response = await json_client.get('/json', headers={'Accept-Encoding': '*;q=0'})
    assert response.status == 406
    assert 'Content-Encoding' not in response.headers
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


async def test_json_guard_error_is_compressed_too(
    json_client: TestClient[web.Request, web.Application],
):
    response = await json_client.get(
        '/json', headers={'Host': 'foreign.example', 'Accept-Encoding': 'gzip'}
    )
    assert response.status == 421
    assert response.headers['Content-Encoding'] == 'gzip'
    assert json.loads(gzip.decompress(await response.read())) == {
        'error': {'code': 'host_not_allowed', 'message': 'This Host is not allowed.'}
    }
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
