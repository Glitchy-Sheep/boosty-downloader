"""
Session-level observer that records every outgoing request in the debug log.

Attached to the shared ClientSession, so API calls, file downloads and
retries all leave a line - the callers never know the log exists.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

from aiohttp import TraceConfig

if TYPE_CHECKING:
    from types import SimpleNamespace

    from aiohttp import ClientSession, TraceRequestStartParams

_log = logging.getLogger(__name__)


def redacted_url(url: str) -> str:
    """
    Make a URL safe for the log file.

    The query string carries signed, expiring credentials - the log is
    meant to be attached to public issues, so only scheme, host and path
    survive.
    """
    parts = urlsplit(url)
    return f'{parts.scheme}://{parts.netloc}{parts.path}'


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
