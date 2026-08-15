"""
Session-level observer that records every outgoing request in the debug log.

Attached to the shared ClientSession, so API calls, file downloads and
retries all leave lines - the callers never know the log exists. Each
request logs its start, the live connection phase and the outcome, so a
hang or a killed handshake is readable straight from the log.
"""

from __future__ import annotations

import logging
from itertools import count
from time import monotonic
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlsplit

from aiohttp import TraceConfig

if TYPE_CHECKING:
    from types import SimpleNamespace

    from aiohttp import (
        ClientSession,
        TraceConnectionCreateEndParams,
        TraceConnectionCreateStartParams,
        TraceConnectionReuseconnParams,
        TraceDnsResolveHostEndParams,
        TraceDnsResolveHostStartParams,
        TraceRequestEndParams,
        TraceRequestExceptionParams,
        TraceRequestStartParams,
    )

_log = logging.getLogger(__name__)

# Concurrent requests interleave in the log; the id ties one request's
# start, connection and outcome lines together.
_request_ids = count(1)


def redacted_url(url: str) -> str:
    """
    Make a URL safe for the log file.

    Query values carry signed, expiring credentials - the log is meant
    to be attached to public issues, so values are masked. Query keys
    stay: they show the request shape without giving anything away.
    """
    parts = urlsplit(url)
    base = f'{parts.scheme}://{parts.netloc}{parts.path}'
    if not parts.query:
        return base
    keys = [key for key, _ in parse_qsl(parts.query, keep_blank_values=True)]
    masked_query = '&'.join(f'{key}=...' for key in keys)
    return f'{base}?{masked_query}'


# Deeper causes add noise, not diagnosis: three levels cover the real
# wrappers (app error -> client error -> OS error).
_MAX_CAUSE_DEPTH = 3


def _error_chain(error: BaseException) -> str:
    """Name the error and up to two of its causes: the chain is the diagnosis."""
    names: list[str] = []
    current: BaseException | None = error
    while current is not None and len(names) < _MAX_CAUSE_DEPTH:
        names.append(type(current).__name__)
        current = current.__cause__
    return ' <- '.join(names)


def _phases(ctx: SimpleNamespace) -> str:
    """
    Summarize the connection phases collected during the request.

    A phase that never finished is timed up to now: a request that died
    mid-connect reports how long the connect lasted.
    """
    if getattr(ctx, 'conn_reused', False):
        return 'conn reused'
    parts: list[str] = []
    dns_time = getattr(ctx, 'dns_time', None)
    dns_started = getattr(ctx, 'dns_started', None)
    conn_started = getattr(ctx, 'conn_started', None)
    if dns_time is not None:
        parts.append(f'dns {dns_time:.3f}s')
    elif dns_started is not None:
        parts.append(f'dns {monotonic() - dns_started:.3f}s')
    elif conn_started is not None:
        parts.append('dns cache')
    if conn_started is not None:
        conn_time = getattr(ctx, 'conn_time', None)
        if conn_time is None:
            conn_time = monotonic() - conn_started
        parts.append(f'conn {conn_time:.3f}s')
    return ', '.join(parts)


async def _log_request_start(
    _session: ClientSession,
    ctx: SimpleNamespace,
    params: TraceRequestStartParams,
) -> None:
    ctx.req_id = next(_request_ids)
    ctx.started = monotonic()
    _log.debug('#%d %s %s', ctx.req_id, params.method, redacted_url(str(params.url)))


async def _log_connection_start(
    _session: ClientSession,
    ctx: SimpleNamespace,
    _params: TraceConnectionCreateStartParams,
) -> None:
    # The live marker: while a connect hangs, this stays the last line.
    ctx.conn_started = monotonic()
    _log.debug('#%d connecting...', ctx.req_id)


async def _mark_connection_end(
    _session: ClientSession,
    ctx: SimpleNamespace,
    _params: TraceConnectionCreateEndParams,
) -> None:
    ctx.conn_time = monotonic() - ctx.conn_started


async def _mark_connection_reused(
    _session: ClientSession,
    ctx: SimpleNamespace,
    _params: TraceConnectionReuseconnParams,
) -> None:
    ctx.conn_reused = True


async def _mark_dns_start(
    _session: ClientSession,
    ctx: SimpleNamespace,
    _params: TraceDnsResolveHostStartParams,
) -> None:
    ctx.dns_started = monotonic()


async def _mark_dns_end(
    _session: ClientSession,
    ctx: SimpleNamespace,
    _params: TraceDnsResolveHostEndParams,
) -> None:
    ctx.dns_time = monotonic() - ctx.dns_started


async def _log_request_end(
    _session: ClientSession,
    ctx: SimpleNamespace,
    params: TraceRequestEndParams,
) -> None:
    elapsed = monotonic() - ctx.started
    phases = _phases(ctx)
    suffix = f' ({phases})' if phases else ''
    _log.debug(
        '#%d -> %d in %.2fs%s', ctx.req_id, params.response.status, elapsed, suffix
    )


async def _log_request_exception(
    _session: ClientSession,
    ctx: SimpleNamespace,
    params: TraceRequestExceptionParams,
) -> None:
    elapsed = monotonic() - ctx.started
    phases = _phases(ctx)
    suffix = f' ({phases})' if phases else ''
    _log.debug(
        '#%d -> FAIL %s in %.2fs%s',
        ctx.req_id,
        _error_chain(params.exception),
        elapsed,
        suffix,
    )


def create_request_trace_config() -> TraceConfig:
    """Build the request observer to attach to the ClientSession."""
    trace_config = TraceConfig()
    trace_config.on_request_start.append(_log_request_start)
    trace_config.on_connection_create_start.append(_log_connection_start)
    trace_config.on_connection_create_end.append(_mark_connection_end)
    trace_config.on_connection_reuseconn.append(_mark_connection_reused)
    trace_config.on_dns_resolvehost_start.append(_mark_dns_start)
    trace_config.on_dns_resolvehost_end.append(_mark_dns_end)
    trace_config.on_request_end.append(_log_request_end)
    trace_config.on_request_exception.append(_log_request_exception)
    return trace_config
