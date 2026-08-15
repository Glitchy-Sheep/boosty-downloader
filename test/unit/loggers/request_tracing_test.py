"""The debug log must tell what happened to a request, not only that it started."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

from boosty_downloader.src.infrastructure.loggers import request_tracing
from boosty_downloader.src.infrastructure.loggers.request_tracing import redacted_url

if TYPE_CHECKING:
    import pytest
    from aiohttp import ClientSession

_LOGGER_NAME = request_tracing.__name__
_SESSION = cast('ClientSession', None)


def _run_hooks(*coros: object) -> None:
    async def runner() -> None:
        for coro in coros:
            await coro  # type: ignore[misc]

    asyncio.run(runner())


def _start_params(
    url: str = 'https://api.boosty.to/v1/blog/x/post/',
) -> SimpleNamespace:
    return SimpleNamespace(method='GET', url=url)


def test_success_outcome_shows_status_timing_and_phases(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without outcomes a slow Boosty looks the same as a dead one."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    ctx = SimpleNamespace(trace_request_ctx=None)

    _run_hooks(
        request_tracing._log_request_start(_SESSION, ctx, _start_params()),
        request_tracing._log_connection_start(_SESSION, ctx, SimpleNamespace()),
        request_tracing._mark_dns_start(_SESSION, ctx, SimpleNamespace()),
        request_tracing._mark_dns_end(_SESSION, ctx, SimpleNamespace()),
        request_tracing._mark_connection_end(_SESSION, ctx, SimpleNamespace()),
        request_tracing._log_request_end(
            _SESSION, ctx, SimpleNamespace(response=SimpleNamespace(status=200))
        ),
    )

    outcome = caplog.messages[-1]
    assert '-> 200 in' in outcome
    assert 'dns' in outcome
    assert 'conn' in outcome


def test_failed_attempt_names_the_error_chain(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A TLS handshake reset by the network must be readable from the log."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    ctx = SimpleNamespace(trace_request_ctx=None)
    error = ConnectionError('cannot connect')
    error.__cause__ = ConnectionResetError('handshake killed')

    _run_hooks(
        request_tracing._log_request_start(_SESSION, ctx, _start_params()),
        request_tracing._log_connection_start(_SESSION, ctx, SimpleNamespace()),
        request_tracing._log_request_exception(
            _SESSION, ctx, SimpleNamespace(exception=error)
        ),
    )

    outcome = caplog.messages[-1]
    assert 'FAIL ConnectionError <- ConnectionResetError' in outcome
    assert 'conn' in outcome, 'the unfinished connect phase must still be timed'


def test_hang_leaves_connecting_as_the_last_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """During a hang the last log line must name the stuck phase."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    ctx = SimpleNamespace(trace_request_ctx=None)

    _run_hooks(
        request_tracing._log_request_start(_SESSION, ctx, _start_params()),
        request_tracing._log_connection_start(_SESSION, ctx, SimpleNamespace()),
    )

    assert caplog.messages[-1].endswith('connecting...')


def test_pooled_connection_is_marked_reused(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A reused connection must not pretend it measured dns and connect."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    ctx = SimpleNamespace(trace_request_ctx=None)

    _run_hooks(
        request_tracing._log_request_start(_SESSION, ctx, _start_params()),
        request_tracing._mark_connection_reused(_SESSION, ctx, SimpleNamespace()),
        request_tracing._log_request_end(
            _SESSION, ctx, SimpleNamespace(response=SimpleNamespace(status=200))
        ),
    )

    assert '(conn reused)' in caplog.messages[-1]


def test_request_lines_share_one_id(caplog: pytest.LogCaptureFixture) -> None:
    """Concurrent requests interleave: without ids the lines are unmatchable."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    ctx = SimpleNamespace(trace_request_ctx=None)

    _run_hooks(
        request_tracing._log_request_start(_SESSION, ctx, _start_params()),
        request_tracing._log_connection_start(_SESSION, ctx, SimpleNamespace()),
        request_tracing._log_request_end(
            _SESSION, ctx, SimpleNamespace(response=SimpleNamespace(status=200))
        ),
    )

    ids = {message.split()[0] for message in caplog.messages}
    assert len(ids) == 1
    assert ids.pop().startswith('#')


def test_retry_attempt_number_lands_in_the_start_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Silent retries hide that a request is dying: attempt 2/5 tells it."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    ctx = SimpleNamespace(trace_request_ctx={'current_attempt': 2}, total_attempts=5)

    _run_hooks(request_tracing._log_request_start(_SESSION, ctx, _start_params()))

    assert caplog.messages[-1].endswith('(attempt 2/5)')


def test_requests_without_retry_context_get_no_attempt_mark(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A request outside RetryClient must not invent attempt numbers."""
    caplog.set_level(logging.DEBUG, logger=_LOGGER_NAME)
    ctx = SimpleNamespace(trace_request_ctx=None)

    _run_hooks(request_tracing._log_request_start(_SESSION, ctx, _start_params()))

    assert '(attempt' not in caplog.messages[-1]


def test_redacted_url_masks_query_values_but_keeps_keys() -> None:
    """Values are working credentials; keys are needed to match the endpoint."""
    url = 'https://cdn.boosty.to/file/181ac169?sig=SECRET&expire=1770000000'

    assert redacted_url(url) == 'https://cdn.boosty.to/file/181ac169?sig=...&expire=...'


def test_redacted_url_keeps_a_plain_url_intact() -> None:
    """Over-cutting would make the log useless for matching failing endpoints."""
    url = 'https://api.boosty.to/v1/blog/author/post/'

    assert redacted_url(url) == url
