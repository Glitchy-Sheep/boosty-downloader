"""
Session-level observer that records every outgoing request in the debug log.

Attached to the shared ClientSession, so API calls, file downloads and
retries all leave a line - the callers never know the log exists.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlsplit

from aiohttp import TraceConfig

if TYPE_CHECKING:
    from types import SimpleNamespace

    from aiohttp import ClientSession, TraceRequestStartParams

_log = logging.getLogger(__name__)


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


async def _log_request_start(
    _session: ClientSession,
    _ctx: SimpleNamespace,
    params: TraceRequestStartParams,
) -> None:
    _log.debug('%s %s', params.method, redacted_url(str(params.url)))


def create_request_trace_config() -> TraceConfig:
    """Build the request observer to attach to the ClientSession."""
    trace_config = TraceConfig()
    trace_config.on_request_start.append(_log_request_start)
    return trace_config
