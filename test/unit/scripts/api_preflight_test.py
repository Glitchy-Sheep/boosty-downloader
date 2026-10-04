from __future__ import annotations

import importlib
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import ModuleType


@pytest.fixture
def preflight(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.syspath_prepend(str(Path(__file__).parents[3] / 'scripts'))
    return importlib.import_module('api_preflight')


@pytest.fixture
def tls_connection(
    preflight: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> tuple[ssl.SSLContext, MagicMock, MagicMock]:
    context = ssl.create_default_context()
    connection = MagicMock()
    handshake = MagicMock()
    monkeypatch.setattr(
        preflight.ssl, 'create_default_context', MagicMock(return_value=context)
    )
    monkeypatch.setattr(preflight.socket, 'create_connection', connection)
    monkeypatch.setattr(context, 'wrap_socket', handshake)
    return context, connection, handshake


@pytest.fixture
def non_utc_timezone(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    try:
        with monkeypatch.context() as patch:
            patch.setenv('TZ', 'MSK-3')
            if hasattr(time, 'tzset'):
                time.tzset()
            yield
    finally:
        if hasattr(time, 'tzset'):
            time.tzset()


@pytest.mark.usefixtures('non_utc_timezone')
def test_verified_certificate_expiry_is_utc(
    preflight: ModuleType,
    tls_connection: tuple[ssl.SSLContext, MagicMock, MagicMock],
    capsys: pytest.CaptureFixture[str],
) -> None:
    context, connection, handshake = tls_connection
    handshake.return_value.__enter__.return_value.getpeercert.return_value = {
        'notAfter': 'Dec  6 15:14:58 2026 GMT',
    }

    expires_at = preflight._get_certificate_expiry(preflight.HOST)

    assert expires_at == datetime(2026, 12, 6, 15, 14, 58, tzinfo=timezone.utc)
    preflight.ssl.create_default_context.assert_called_once_with()
    connection.assert_called_once_with(('api.boosty.to', 443), timeout=10)
    handshake.assert_called_once_with(
        connection.return_value.__enter__.return_value, server_hostname='api.boosty.to'
    )
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    preflight.check_tls()
    output = capsys.readouterr().out
    assert 'TLS verification passed.' in output
    assert 'Server certificate valid until: 2026-12-06 15:14:58 UTC' in output


@pytest.mark.parametrize('certificate', [None, {}])
def test_missing_expiry_does_not_invent_a_date(
    preflight: ModuleType,
    tls_connection: tuple[ssl.SSLContext, MagicMock, MagicMock],
    capsys: pytest.CaptureFixture[str],
    certificate: dict[str, str] | None,
) -> None:
    _, _, handshake = tls_connection
    handshake.return_value.__enter__.return_value.getpeercert.return_value = certificate

    preflight.check_tls()

    output = capsys.readouterr().out
    assert 'TLS verification passed.' in output
    assert 'expiry is unavailable' in output
    assert 'valid until' not in output


@pytest.mark.parametrize(
    'reason', ['certificate has expired', 'unable to get local issuer certificate']
)
async def test_certificate_failure_exits_before_reading_certificate_or_calling_api(
    preflight: ModuleType,
    tls_connection: tuple[ssl.SSLContext, MagicMock, MagicMock],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reason: str,
) -> None:
    _, _, handshake = tls_connection
    error = ssl.SSLCertVerificationError(1, reason)
    error.verify_message = reason
    handshake.side_effect = error
    monkeypatch.setattr(preflight, 'load_config', MagicMock(return_value=object()))
    fetch = AsyncMock()
    monkeypatch.setattr(preflight, 'fetch_author_posts', fetch)

    with pytest.raises(SystemExit, match='1'):
        await preflight.main()

    handshake.return_value.__enter__.return_value.getpeercert.assert_not_called()
    fetch.assert_not_awaited()
    output = capsys.readouterr().out
    assert 'TLS certificate verification failed for api.boosty.to:' in output
    assert reason in output
    assert 'Check your system date/time and trusted CA certificates.' in output
    assert 'server certificate or a CA in its chain' in output
    assert 'TLS verification passed' not in output
    assert 'Traceback' not in output


@pytest.mark.parametrize(
    'error', [TimeoutError('timed out'), ssl.SSLError('protocol failure')]
)
def test_connection_failures_are_not_reported_as_expired_certificates(
    preflight: ModuleType,
    tls_connection: tuple[ssl.SSLContext, MagicMock, MagicMock],
    capsys: pytest.CaptureFixture[str],
    error: OSError,
) -> None:
    _, connection, _ = tls_connection
    connection.side_effect = error

    with pytest.raises(SystemExit, match='1'):
        preflight.check_tls()

    output = capsys.readouterr().out
    assert 'Could not establish a TLS connection to api.boosty.to:' in output
    assert str(error) in output
    assert 'Check your network' in output
    assert 'certificate verification failed' not in output
    assert 'trusted CA' not in output


async def test_main_verifies_tls_before_using_credentials(
    preflight: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls = MagicMock()
    config = object()
    calls.attach_mock(MagicMock(return_value=config), 'config')
    calls.attach_mock(MagicMock(), 'tls')
    calls.attach_mock(AsyncMock(), 'fetch')
    monkeypatch.setattr(preflight, 'load_config', calls.config)
    monkeypatch.setattr(preflight, 'check_tls', calls.tls)
    monkeypatch.setattr(preflight, 'fetch_author_posts', calls.fetch)

    await preflight.main()

    assert [call[0] for call in calls.mock_calls] == ['config', 'tls', 'fetch']
    calls.fetch.assert_awaited_once_with(config, preflight.TITLE, limit=1)
    assert (
        'Credentials are live - running the integration suite'
        in capsys.readouterr().out
    )
