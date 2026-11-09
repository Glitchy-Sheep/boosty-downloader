"""Blog requests isolate network failures and release connections after interruption."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import pytest
from aiohttp import ClientPayloadError, ClientTimeout, TCPConnector, web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient

from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPIClient,
    BoostyAPITransportError,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable

AUTHOR = 'fixture-author'


@asynccontextmanager
async def _blog_client(
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    *,
    timeout: ClientTimeout | None = None,
) -> AsyncGenerator[BoostyAPIClient, None]:
    app = web.Application()
    app.router.add_get(f'/v1/blog/{AUTHOR}', handler)
    async with (
        TestServer(app) as server,
        RetryClient(
            connector=TCPConnector(limit=1),
            timeout=timeout,
            retry_options=ExponentialRetry(attempts=1),
        ) as session,
    ):
        yield BoostyAPIClient(session, base_url=server.make_url('/v1/'))


async def test_incomplete_blog_body_maps_payload_error_and_releases_connection() -> (
    None
):
    calls = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal calls
        calls += 1
        if calls > 1:
            return web.json_response({'title': 'Complete blog'})
        response = web.StreamResponse(
            headers={'Content-Type': 'application/json', 'Content-Length': '100'}
        )
        await response.prepare(request)
        await response.write(b'{"title":')
        assert request.transport is not None
        request.transport.close()
        return response

    async with _blog_client(handler) as client:
        with pytest.raises(BoostyAPITransportError) as caught:
            await client.get_blog_info(AUTHOR)
        recovered = await asyncio.wait_for(client.get_blog_info(AUTHOR), timeout=1)

    assert isinstance(caught.value.__cause__, ClientPayloadError)
    assert recovered.title == 'Complete blog'
    assert calls == 2


@pytest.mark.parametrize('before_headers', [False, True])
async def test_blog_total_timeout_is_an_api_error_and_releases_connection(
    *, before_headers: bool
) -> None:
    stop = asyncio.Event()
    calls = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal calls
        calls += 1
        if calls > 1:
            return web.json_response({'title': 'Complete blog'})
        response = web.StreamResponse(headers={'Content-Type': 'application/json'})
        if not before_headers:
            await response.prepare(request)
            await response.write(b'{"title":')
        await stop.wait()
        return response

    async with _blog_client(handler, timeout=ClientTimeout(total=1)) as client:
        try:
            with pytest.raises(BoostyAPITransportError) as caught:
                await client.get_blog_info(AUTHOR)
        finally:
            stop.set()
        recovered = await client.get_blog_info(AUTHOR)

    assert isinstance(caught.value.__cause__, asyncio.TimeoutError)
    assert recovered.title == 'Complete blog'
    assert calls == 2


@pytest.mark.parametrize('before_headers', [False, True])
async def test_blog_cancellation_propagates_and_releases_connection(
    *, before_headers: bool
) -> None:
    entered = asyncio.Event()
    stop = asyncio.Event()
    calls = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal calls
        calls += 1
        if calls > 1:
            return web.json_response({'title': 'Complete blog'})
        response = web.StreamResponse(headers={'Content-Type': 'application/json'})
        if not before_headers:
            await response.prepare(request)
            await response.write(b'{"title":')
        entered.set()
        await stop.wait()
        return response

    async with _blog_client(handler) as client:
        request = asyncio.create_task(client.get_blog_info(AUTHOR))
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            request.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request
        finally:
            request.cancel()
            stop.set()
        recovered = await asyncio.wait_for(client.get_blog_info(AUTHOR), timeout=1)

    assert recovered.title == 'Complete blog'
    assert calls == 2
