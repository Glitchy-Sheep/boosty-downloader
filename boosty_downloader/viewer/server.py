"""Bind the local viewer and report its actual addresses after startup."""

from __future__ import annotations

import asyncio
import socket
import webbrowser
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from errno import EADDRINUSE
from typing import TYPE_CHECKING, Final

from aiohttp import web

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

DEFAULT_PORT: Final = 8314
MAX_PORT: Final = 65535


@dataclass(frozen=True, slots=True)
class ServerOptions:
    """An omitted port permits fallback; an explicit port is always respected."""

    port: int | None = None
    lan: bool = False
    open_browser: bool = True

    def __post_init__(self) -> None:
        """Reject invalid explicit ports before creating application resources."""
        if self.port is not None and not 1 <= self.port <= MAX_PORT:
            message = f'Viewer port must be between 1 and {MAX_PORT}'
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class ServerAddresses:
    """Addresses of the listener that has successfully bound."""

    port: int
    network: tuple[str, ...] = ()

    @property
    def local(self) -> str:
        """Stable local address, independent of DNS and network interfaces."""
        return f'http://127.0.0.1:{self.port}/'


class ViewerStartupError(RuntimeError):
    """The requested local listener could not be started."""


def lan_address() -> str | None:
    """Find the outgoing local IPv4 address without sending a network packet."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(('10.255.255.255', 1))
        except OSError:
            return None
        return str(probe.getsockname()[0])


def _addresses(port: int, *, lan: bool) -> ServerAddresses:
    if not lan:
        return ServerAddresses(port=port)
    network: list[str] = []
    if address := lan_address():
        network.append(f'http://{address}:{port}/')
    hostname = socket.gethostname().rstrip('.').removesuffix('.local')
    if hostname:
        network.append(f'http://{hostname}.local:{port}/')
    return ServerAddresses(port=port, network=tuple(network))


async def _bind(runner: web.AppRunner, options: ServerOptions) -> int:
    host = '0.0.0.0' if options.lan else '127.0.0.1'  # noqa: S104 - --lan is explicit
    port = options.port if options.port is not None else DEFAULT_PORT
    while port <= MAX_PORT:
        # The reported localhost URL must reach this listener, including with --lan.
        site = web.TCPSite(runner, host, port, reuse_address=False)
        try:
            await site.start()
        except OSError as error:
            await site.stop()
            if options.port is not None or error.errno != EADDRINUSE:
                message = f'Cannot start viewer on {host}:{port}: {error}'
                raise ViewerStartupError(message) from error
            port += 1
        else:
            return port
    message = f'No free viewer port from {DEFAULT_PORT} through {MAX_PORT}'
    raise ViewerStartupError(message)


@asynccontextmanager
async def running_server(
    app: web.Application, options: ServerOptions
) -> AsyncGenerator[ServerAddresses, None]:
    """Own the listener and app resources across startup, cancellation and shutdown."""
    runner = web.AppRunner(app, access_log=None)
    try:
        await runner.setup()
        port = await _bind(runner, options)
        yield _addresses(port, lan=options.lan)
    finally:
        await runner.cleanup()


async def serve_forever(
    app: web.Application,
    options: ServerOptions,
    on_started: Callable[[ServerAddresses], None],
) -> None:
    """Announce the listener, optionally open the browser, and wait for shutdown."""
    async with running_server(app, options) as addresses:
        on_started(addresses)
        if options.open_browser:
            with suppress(OSError, webbrowser.Error):
                await asyncio.to_thread(webbrowser.open, addresses.local)
        await asyncio.Event().wait()


def serve(
    app: web.Application,
    *,
    options: ServerOptions,
    on_started: Callable[[ServerAddresses], None],
) -> None:
    """Serve until Ctrl+C; a startup failure never opens the browser."""
    with suppress(KeyboardInterrupt):
        asyncio.run(serve_forever(app, options, on_started))
