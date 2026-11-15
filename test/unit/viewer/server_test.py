"""Actual listener ownership, port fallback and browser startup ordering."""

from __future__ import annotations

import asyncio
import socket
from contextlib import contextmanager
from errno import EACCES, EADDRINUSE
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, call, patch

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
    from collections.abc import Callable, Generator
    from ssl import SSLContext


@contextmanager
def _occupied_port(
    host: str = '127.0.0.1', *, exclusive: bool = False
) -> Generator[int, None, None]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if exclusive and (option := getattr(socket, 'SO_EXCLUSIVEADDRUSE', None)):
            listener.setsockopt(socket.SOL_SOCKET, option, 1)
        listener.bind((host, 0))
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


@pytest.mark.parametrize('lan', [False, True])
async def test_explicit_busy_port_fails_and_cleans_up(*, lan: bool) -> None:
    app = _app()
    events: list[str] = []

    async def cleanup(_: web.Application) -> None:
        events.append('cleanup')

    app.on_cleanup.append(cleanup)
    with _occupied_port() as busy, pytest.raises(ViewerStartupError, match=str(busy)):
        async with running_server(app, ServerOptions(port=busy, lan=lan)):
            pytest.fail('An explicitly busy port must not be replaced')
    assert events == ['cleanup']


@pytest.mark.parametrize('error_code', [EACCES, EADDRINUSE])
async def test_site_startup_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, error_code: int
) -> None:
    calls: list[str] = []

    async def denied(self: web.SockSite) -> None:
        await web.BaseSite.start(self)
        calls.append('bind')
        raise OSError(error_code, 'startup denied')

    monkeypatch.setattr(web.SockSite, 'start', denied)
    with pytest.raises(ViewerStartupError, match='startup denied'):
        async with running_server(_app(), ServerOptions()):
            pytest.fail('A failure after binding must stop startup')
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


@pytest.mark.parametrize('lan', [False, True])
async def test_existing_exclusive_wildcard_listener_uses_next_port(
    monkeypatch: pytest.MonkeyPatch, *, lan: bool
) -> None:
    with _occupied_port('0.0.0.0', exclusive=True) as busy:  # noqa: S104
        monkeypatch.setattr(server, 'DEFAULT_PORT', busy)
        async with running_server(_app(), ServerOptions(lan=lan)) as addresses:
            assert addresses.port > busy
            await _assert_reachable(addresses)


async def test_existing_wildcard_listener_does_not_capture_viewer_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _occupied_port('0.0.0.0') as busy:  # noqa: S104
        monkeypatch.setattr(server, 'DEFAULT_PORT', busy)
        async with running_server(_app(), ServerOptions()) as addresses:
            # Windows can reserve loopback within a nonexclusive wildcard listener.
            await _assert_reachable(addresses)


async def test_windows_exclusivity_is_enabled_before_bind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exclusive_option = -1
    monkeypatch.setattr(socket, 'SO_EXCLUSIVEADDRUSE', exclusive_option, raising=False)
    listener = MagicMock(spec=socket.socket)
    listener.__enter__.return_value = listener
    site = MagicMock(spec=web.SockSite)
    site.start = AsyncMock()
    runner = MagicMock(spec=web.AppRunner)
    with (
        patch.object(socket, 'socket', return_value=listener),
        patch.object(web, 'SockSite', return_value=site) as create_site,
    ):
        assert await server._start_site(  # pyright: ignore[reportPrivateUsage]
            runner, '127.0.0.1', 8314, allow_fallback=True
        )
    assert listener.method_calls == [
        call.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0),
        call.setsockopt(socket.SOL_SOCKET, exclusive_option, 1),
        call.bind(('127.0.0.1', 8314)),
    ]
    create_site.assert_called_once_with(runner, listener)
    site.start.assert_awaited_once()
    listener.__exit__.assert_not_called()


@pytest.mark.parametrize('allow_fallback', [False, True])
def test_windows_exclusive_bind_denial_only_retries_automatic_port(
    monkeypatch: pytest.MonkeyPatch, *, allow_fallback: bool
) -> None:
    denial = OSError(EACCES, 'Windows exclusive bind denied')
    monkeypatch.setattr(denial, 'winerror', 10013, raising=False)
    listener = MagicMock(spec=socket.socket)
    listener.bind.side_effect = denial
    if allow_fallback:
        assert not server._bind_candidate(  # pyright: ignore[reportPrivateUsage]
            listener, '127.0.0.1', 8314, allow_fallback=True
        )
    else:
        with pytest.raises(OSError, match='Windows exclusive bind denied'):
            server._bind_candidate(  # pyright: ignore[reportPrivateUsage]
                listener, '127.0.0.1', 8314, allow_fallback=False
            )


def test_other_bind_permission_error_is_not_retryable() -> None:
    listener = MagicMock(spec=socket.socket)
    listener.bind.side_effect = OSError(EACCES, 'bind denied')
    with pytest.raises(OSError, match='bind denied'):
        server._bind_candidate(  # pyright: ignore[reportPrivateUsage]
            listener, '127.0.0.1', 8314, allow_fallback=True
        )


@pytest.mark.parametrize(
    'error', [OSError(EACCES, 'setup denied'), asyncio.CancelledError()]
)
async def test_failed_site_start_closes_bound_socket(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    listeners: list[socket.socket] = []
    configure = server._configure_listener  # pyright: ignore[reportPrivateUsage]

    def track_socket(listener: socket.socket) -> None:
        listeners.append(listener)
        configure(listener)

    async def fail(self: web.SockSite) -> None:
        await web.BaseSite.start(self)
        raise error

    monkeypatch.setattr(server, '_configure_listener', track_socket)
    monkeypatch.setattr(web.SockSite, 'start', fail)
    with _occupied_port() as busy:
        monkeypatch.setattr(server, 'DEFAULT_PORT', busy)
        with pytest.raises((ViewerStartupError, asyncio.CancelledError)):
            async with running_server(_app(), ServerOptions()):
                pytest.fail('Startup failure must not expose a server')
    assert len(listeners) >= 2
    assert all(listener.fileno() == -1 for listener in listeners)


@pytest.mark.parametrize('cancel_count', [1, 2])
async def test_cancellation_during_socket_handoff_allows_next_server_to_respond(
    monkeypatch: pytest.MonkeyPatch,
    cancel_count: int,
) -> None:
    loop = asyncio.get_running_loop()
    owner = asyncio.current_task()
    assert owner is not None
    create_server = loop.create_server
    bound_listener: socket.socket | None = None
    bound_port: int | None = None

    async def cancel_owner(
        protocol_factory: Callable[[], asyncio.Protocol],
        *,
        sock: socket.socket,
        ssl: SSLContext | None,
        backlog: int,
    ) -> asyncio.Server:
        nonlocal bound_listener, bound_port
        bound_listener = sock
        bound_port = int(sock.getsockname()[1])
        loop.call_soon(owner.cancel)
        listener_server = await create_server(
            protocol_factory, sock=sock, ssl=ssl, backlog=backlog
        )
        if cancel_count == 2:
            loop.call_soon(owner.cancel)
            await asyncio.sleep(0)
        return listener_server

    with monkeypatch.context() as startup:
        startup.setattr(loop, 'create_server', cancel_owner)
        with pytest.raises(asyncio.CancelledError):
            async with running_server(_app(), ServerOptions()):
                pytest.fail('Cancelled startup must not expose a server')
    assert bound_listener is not None
    assert bound_listener.fileno() == -1
    assert bound_port is not None
    async with running_server(_app(), ServerOptions(port=bound_port)) as addresses:
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
