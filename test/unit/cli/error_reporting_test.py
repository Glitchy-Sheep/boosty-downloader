"""Network failures must tell the user what broke, not "check your internet"."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp.client_exceptions import ClientConnectorDNSError, ClientError
from aiohttp.client_reqrep import ConnectionKey

from boosty_downloader.cli.error_reporting import report_network_error

if TYPE_CHECKING:
    import pytest


def _dns_error(host: str) -> ClientConnectorDNSError:
    """Build the error the same way aiohttp does on a failed DNS lookup."""
    key = ConnectionKey(
        host=host,
        port=443,
        is_ssl=True,
        ssl=True,
        proxy=None,
        proxy_auth=None,
        proxy_headers_hash=None,
    )
    return ClientConnectorDNSError(key, OSError(8, 'nodename nor servname provided'))


def test_dns_error_names_the_host_and_the_dns_cause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Issue #109: the DNS failure used to hide behind a generic network message."""
    with caplog.at_level(logging.INFO, logger='Boosty_Downloader'):
        report_network_error(_dns_error('api.boosty.to'))

    assert 'DNS' in caplog.text
    assert 'api.boosty.to' in caplog.text


def test_generic_network_error_shows_the_real_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A swallowed exception type leaves nothing to diagnose or report."""
    with caplog.at_level(logging.INFO, logger='Boosty_Downloader'):
        report_network_error(ClientError('connection reset'))

    assert 'ClientError' in caplog.text
    assert 'connection reset' in caplog.text
    assert 'DNS' not in caplog.text


def test_every_network_error_points_at_the_debug_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Without the pointer the user cannot produce a diagnosable bug report."""
    with caplog.at_level(logging.INFO, logger='Boosty_Downloader'):
        report_network_error(ClientError('boom'))

    assert '--debug' in caplog.text
    assert 'boosty-downloader-debug.log' in caplog.text
