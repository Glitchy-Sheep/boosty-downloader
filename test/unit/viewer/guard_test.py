from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from multidict import CIMultiDict

from boosty_downloader.viewer.guard import (
    guard_requests,
    is_host_allowed,
    is_write_allowed,
    secure_response,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@pytest.fixture(autouse=True)
def machine_name(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        'boosty_downloader.viewer.guard.socket.gethostname', lambda: 'desk.local'
    )


@pytest.mark.parametrize(
    'host',
    [
        'localhost',
        'LOCALHOST.',
        'localhost:9',
        '127.0.0.1:8314',
        '192.168.2.4:9876',
        '[::1]:123',
        '[2001:db8::1]',
        'desk',
        'desk.local:9999',
    ],
)
def test_known_hosts_are_allowed_on_any_port(host: str):
    request = make_mocked_request('GET', '/', headers={'Host': host})
    assert is_host_allowed(request)


@pytest.mark.parametrize(
    'host',
    [
        'foreign.example',
        'desk.lan',
        'localhost.foreign.example',
        'localhost..',
        'foreign@localhost',
        'localhost/foreign',
        'localhost?query',
        'localhost#fragment',
        'localhost,foreign.example',
        ' localhost',
        'localhost\t',
        'localhost\x7f',
        'localhost:',
        'localhost:65536',
        'localhost:-1',
        'localhost:８０',
        '[::1]foreign',
        '[::1]:',
        '[::1',
        '::1',
        '',
    ],
)
def test_malformed_or_foreign_hosts_are_refused(host: str):
    request = make_mocked_request('GET', '/', headers={'Host': host})
    assert not is_host_allowed(request)


def test_duplicate_host_headers_are_refused():
    headers = CIMultiDict([('Host', 'localhost'), ('Host', 'foreign.example')])
    assert not is_host_allowed(make_mocked_request('GET', '/', headers=headers))


async def _ok(request: web.Request) -> web.Response:
    del request
    return web.json_response({'ok': True})


@pytest.fixture
async def guard_client() -> AsyncIterator[TestClient[web.Request, web.Application]]:
    app = web.Application(middlewares=[guard_requests])
    app.on_response_prepare.append(secure_response)
    app.router.add_route('*', '/', _ok)
    async with TestClient(TestServer(app)) as client:
        yield client


async def test_foreign_host_gets_json_refusal(
    guard_client: TestClient[web.Request, web.Application],
):
    response = await guard_client.get('/', headers={'Host': 'foreign.example'})
    assert response.status == 421
    assert await response.json() == {'error': 'This Host is not allowed.'}
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']


async def test_foreign_page_gets_actual_localhost_address(
    guard_client: TestClient[web.Request, web.Application],
):
    response = await guard_client.get(
        '/', headers={'Host': 'foreign.example:65500', 'Accept': 'text/html'}
    )
    assert response.status == 421
    body = await response.text()
    assert f'http://localhost:{guard_client.port}/' in body
    assert 'foreign.example' not in body
    assert response.headers['Content-Type'].startswith('text/html')
    assert response.headers['Cache-Control'] == 'no-store'


@pytest.mark.parametrize('method', ['POST', 'PUT', 'PATCH', 'DELETE'])
async def test_writes_require_json(
    guard_client: TestClient[web.Request, web.Application], method: str
):
    response = await guard_client.request(method, '/', data='{}')
    assert response.status == 403


@pytest.mark.parametrize(
    'origin',
    [
        'null',
        'https://localhost:8314',
        'http://foreign.example:8314',
        'http://localhost:8315',
        'http://localhost.:8314',
        'http://localhost:8314/path',
        'http://localhost:8314/',
        'http://localhost:8314?',
        'http://localhost:8314#',
        '//localhost:8314',
        'http://foreign@localhost:8314',
    ],
)
async def test_foreign_or_malformed_origins_are_refused(
    guard_client: TestClient[web.Request, web.Application], origin: str
):
    response = await guard_client.post(
        '/', json={}, headers={'Host': 'localhost:8314', 'Origin': origin}
    )
    assert response.status == 403
    assert 'Access-Control-Allow-Origin' not in response.headers


@pytest.mark.parametrize('fetch_site', ['cross-site', 'same-site', 'none', ''])
async def test_fetch_metadata_requires_same_origin(
    guard_client: TestClient[web.Request, web.Application], fetch_site: str
):
    response = await guard_client.post(
        '/', json={}, headers={'Sec-Fetch-Site': fetch_site}
    )
    assert response.status == 403


@pytest.mark.parametrize('origin', [None, 'http://localhost:8314'])
async def test_same_origin_or_non_browser_json_is_allowed(
    guard_client: TestClient[web.Request, web.Application], origin: str | None
):
    headers = {'Host': 'localhost:8314', 'Sec-Fetch-Site': 'same-origin'}
    if origin is not None:
        headers['Origin'] = origin
    response = await guard_client.post('/', json={}, headers=headers)
    assert response.status == 200


def test_default_origin_port_matches_host_without_port():
    request = make_mocked_request(
        'POST',
        '/',
        headers={
            'Host': 'localhost',
            'Origin': 'http://localhost:80',
            'Content-Type': 'application/json',
        },
    )
    assert is_write_allowed(request)


def test_multiple_origin_headers_are_refused():
    headers = CIMultiDict(
        [
            ('Host', 'localhost'),
            ('Content-Type', 'application/json'),
            ('Origin', 'http://localhost'),
            ('Origin', 'http://foreign.example'),
        ]
    )
    assert not is_write_allowed(make_mocked_request('POST', '/', headers=headers))


async def test_cors_preflight_is_not_enabled(
    guard_client: TestClient[web.Request, web.Application],
):
    response = await guard_client.options(
        '/',
        headers={
            'Origin': 'http://foreign.example',
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type',
        },
    )
    assert 'Access-Control-Allow-Origin' not in response.headers


def test_multiple_content_types_are_refused():
    headers = CIMultiDict(
        [
            ('Host', 'localhost'),
            ('Content-Type', 'application/json'),
            ('Content-Type', 'text/plain'),
        ]
    )
    assert not is_write_allowed(make_mocked_request('POST', '/', headers=headers))
