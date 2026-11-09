from __future__ import annotations

from typing import TYPE_CHECKING, cast

from aiohttp.test_utils import TestClient, TestServer

from boosty_downloader.viewer.app import LIBRARY_READER, LibraryNotice, create_app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from aiohttp import web

    from boosty_downloader.application.ports import LibraryReader


def test_factory_retains_the_injected_reader_without_calling_it(tmp_path: Path):
    reader = cast('LibraryReader', object())
    app = create_app(reader=reader, static_directory=tmp_path)
    assert app[LIBRARY_READER] is reader
    assert list(tmp_path.iterdir()) == []


async def test_library_notice_replaces_the_ui_and_escapes_data(tmp_path: Path):
    (tmp_path / 'index.html').write_text('Do not show the shell', encoding='utf-8')
    notice = LibraryNotice('Old <library>', 'Choose another folder: <script> & "path"')
    app = create_app(reader=None, notice=notice, static_directory=tmp_path)
    async with TestClient(TestServer(app)) as client:
        response = await client.get('/a/old/post')
        body = await response.text()
        assert response.status == 200
        assert 'Do not show the shell' not in body
        assert '&lt;script&gt;' in body
        assert 'Old &lt;library&gt;' in body
        assert '<script>' not in body
        assert response.headers['Cache-Control'] == 'no-cache'
        assert response.headers['X-Frame-Options'] == 'DENY'
        unknown = await client.get('/api/authors')
        assert unknown.status == 404
        assert await unknown.json() == {
            'error': {'code': 'not_found', 'message': 'Not found.'}
        }
        assert unknown.headers['X-Content-Type-Options'] == 'nosniff'


async def test_unexpected_error_retains_response_security_headers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    async def fail(self: object, request: web.Request) -> web.Response:
        del self, request
        message = 'Injected route failure'
        raise RuntimeError(message)

    monkeypatch.setattr('boosty_downloader.viewer.app.StaticUI.respond', fail)
    app = create_app(reader=None, static_directory=tmp_path)
    async with TestClient(TestServer(app)) as client:
        response = await client.get('/')
        assert response.status == 500
        assert response.headers['X-Content-Type-Options'] == 'nosniff'
        assert response.headers['Referrer-Policy'] == 'no-referrer'
        assert response.headers['X-Frame-Options'] == 'DENY'
