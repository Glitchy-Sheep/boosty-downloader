"""Actual listener ownership, port fallback and browser startup ordering."""

from __future__ import annotations

import asyncio
import socket
from contextlib import contextmanager
from errno import EACCES
from typing import TYPE_CHECKING

import pytest
from aiohttp import ClientSession, ClientTimeout, web

from boosty_downloader.viewer import server
from boosty_downloader.viewer.server import (
    ServerAddresses,
    ServerOptions,
    ViewerStartupError,
    running_server,
)

if TYPE_CHECKING:
    from collections.abc import Generator


@contextmanager
def _occupied_port() -> Generator[int, None, None]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        yield int(listener.getsockname()[1])


async def _hello(_: web.Request) -> web.Response:
    return web.Response(text='viewer ready')


def _app() -> web.Application:
    app = web.Application()
    app.router.add_get('/', _hello)
    return app


async def _assert_reachable(addresses: ServerAddresses) -> None:
    async with (
        ClientSession(timeout=ClientTimeout(total=5)) as client,
        client.get(addresses.local) as response,
    ):
        assert response.status == 200
        assert await response.text() == 'viewer ready'


def _assert_released(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', port))


async def test_busy_default_uses_next_available_port_and_releases_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _occupied_port() as busy:
        monkeypatch.setattr(server, 'DEFAULT_PORT', busy)
        async with running_server(
            _app(), ServerOptions(open_browser=False)
        ) as addresses:
            assert addresses.port > busy
            assert addresses.network == ()
            await _assert_reachable(addresses)
    _assert_released(addresses.port)


async def test_explicit_busy_port_fails_and_cleans_up() -> None:
    app = _app()
    events: list[str] = []

    async def cleanup(_: web.Application) -> None:
        events.append('cleanup')

    app.on_cleanup.append(cleanup)
    with _occupied_port() as busy, pytest.raises(ViewerStartupError, match=str(busy)):
        async with running_server(app, ServerOptions(port=busy)):
            pytest.fail('An explicitly busy port must not be replaced')
    assert events == ['cleanup']


async def test_non_address_in_use_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def denied(self: web.TCPSite) -> None:
        await web.BaseSite.start(self)
        calls.append('bind')
        raise OSError(EACCES, 'permission denied')

    monkeypatch.setattr(web.TCPSite, 'start', denied)
    with pytest.raises(ViewerStartupError, match='permission denied'):
        async with running_server(_app(), ServerOptions()):
            pytest.fail('Permission failure must stop startup')
    assert calls == ['bind']


async def test_no_free_default_port_reports_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _occupied_port() as busy:
        monkeypatch.setattr(server, 'DEFAULT_PORT', busy)
        monkeypatch.setattr(server, 'MAX_PORT', busy)
        with pytest.raises(ViewerStartupError, match='No free viewer port'):
            async with running_server(_app(), ServerOptions()):
                pytest.fail('The exhausted range must fail')


async def test_lan_reports_bound_port_ip_and_machine_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(server, 'lan_address', lambda: '192.0.2.8')
    monkeypatch.setattr(socket, 'gethostname', lambda: 'sample-machine.local')
    with _occupied_port() as busy:
        monkeypatch.setattr(server, 'DEFAULT_PORT', busy)
        async with running_server(_app(), ServerOptions(lan=True)) as addresses:
            assert addresses.port > busy
            assert addresses.network == (
                f'http://192.0.2.8:{addresses.port}/',
                f'http://sample-machine.local:{addresses.port}/',
            )
            await _assert_reachable(addresses)


async def test_browser_opens_after_start_and_cancellation_closes_listener(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop = asyncio.get_running_loop()
    started: asyncio.Future[ServerAddresses] = loop.create_future()
    opened: asyncio.Future[str] = loop.create_future()

    def open_browser(url: str) -> bool:
        assert started.done()
        loop.call_soon_threadsafe(opened.set_result, url)
        return True

    monkeypatch.setattr(server.webbrowser, 'open', open_browser)
    with _occupied_port() as busy:
        monkeypatch.setattr(server, 'DEFAULT_PORT', busy)
        task = asyncio.create_task(
            server.serve_forever(_app(), ServerOptions(), started.set_result)
        )
        try:
            addresses = await asyncio.wait_for(started, timeout=5)
            assert await asyncio.wait_for(opened, timeout=5) == addresses.local
            await _assert_reachable(addresses)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    _assert_released(addresses.port)


async def test_no_open_never_calls_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    started: asyncio.Future[ServerAddresses] = (
        asyncio.get_running_loop().create_future()
    )

    def forbidden(_: str) -> bool:
        pytest.fail('--no-open must not launch a browser')

    monkeypatch.setattr(server.webbrowser, 'open', forbidden)
    with _occupied_port() as busy:
        monkeypatch.setattr(server, 'DEFAULT_PORT', busy)
        task = asyncio.create_task(
            server.serve_forever(
                _app(), ServerOptions(open_browser=False), started.set_result
            )
        )
        try:
            await asyncio.wait_for(started, timeout=5)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task


@pytest.mark.parametrize('port', [0, -1, 65536])
def test_explicit_port_is_validated_before_startup(port: int) -> None:
    with pytest.raises(ValueError, match='port must be between'):
        ServerOptions(port=port)
