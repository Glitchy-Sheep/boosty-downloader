"""The account token travels only to the API, never to media hosts.

Built through the real AppEnvironment wiring: a local server records the
headers each session actually sends.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry
from yarl import URL

from boosty_downloader.application.di.app_environment import AppEnvironment
from boosty_downloader.infrastructure.loggers.base import RichLogger

if TYPE_CHECKING:
    from pathlib import Path

TOKEN = 'Bearer test-token'  # noqa: S105 - a fake for header assertions


async def test_only_the_api_session_carries_credentials(tmp_path: Path) -> None:
    """The bug: one shared session sent the account token to every media host."""
    seen: dict[str, dict[str, str | None]] = {}

    async def handler(request: web.Request) -> web.Response:
        seen[request.path] = {
            'auth': request.headers.get('Authorization'),
            'cookie': request.headers.get('Cookie'),
        }
        return web.json_response({})

    app = web.Application()
    app.router.add_get('/{tail:.*}', handler)
    server = TestServer(app)
    await server.start_server()
    try:
        # unsafe=True: the test server lives on a bare IP, and the stdlib
        # jar refuses to store cookies for IPs otherwise.
        jar = aiohttp.CookieJar(unsafe=True)
        jar.update_cookies({'session': 'secret'}, URL(str(server.make_url('/'))))

        config = AppEnvironment.AppConfig(
            author_name='author',
            target_directory=tmp_path,
            boosty_headers={'Authorization': TOKEN},
            boosty_cookies_jar=jar,
            retry_options=ExponentialRetry(attempts=1),
            request_delay_seconds=0,
            logger=RichLogger('credentials-scope-test'),
        )
        async with AppEnvironment(config) as env:
            await env.boosty_api_client.session.get(server.make_url('/api'))
            await env.downloading_retry_client.get(server.make_url('/media'))

        assert seen['/api']['auth'] == TOKEN
        assert seen['/api']['cookie'] == 'session=secret'
        assert seen['/media']['auth'] is None, 'the token leaked to a media host'
        assert seen['/media']['cookie'] is None, 'cookies leaked to a media host'
    finally:
        await server.close()
