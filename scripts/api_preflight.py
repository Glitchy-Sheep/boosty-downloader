"""Preflight for `task test:api`: verify ./.env and live credentials before pytest."""

from __future__ import annotations

import asyncio
import socket
import ssl
from datetime import datetime, timezone

import rich
from _integration_env import fail, fetch_author_posts, load_config
from rich.markup import escape

TITLE = 'test:api'
HOST = 'api.boosty.to'


def _get_certificate_expiry(hostname: str) -> datetime | None:
    context = ssl.create_default_context()
    with (
        socket.create_connection((hostname, 443), timeout=10) as sock,
        context.wrap_socket(sock, server_hostname=hostname) as tls_socket,
    ):
        certificate = tls_socket.getpeercert()
    not_after = certificate.get('notAfter') if certificate else None
    if not isinstance(not_after, str):
        return None
    return datetime.fromtimestamp(ssl.cert_time_to_seconds(not_after), timezone.utc)


def check_tls() -> None:
    """Verify the API certificate and show its expiry or an actionable failure."""
    try:
        expires_at = _get_certificate_expiry(HOST)
    except ssl.SSLCertVerificationError as error:
        fail(
            TITLE,
            f'❌ TLS certificate verification failed for {HOST}:\n'
            f'{escape(error.verify_message)}.\n\n'
            'Check your system date/time and trusted CA certificates.\n'
            'The error may refer to the server certificate or a CA in its chain.',
        )
    except OSError as error:
        fail(
            TITLE,
            f'❌ Could not establish a TLS connection to {HOST}:\n'
            f'{escape(str(error))}\n\nCheck your network and try again.',
        )
    rich.print('[green]✅ TLS verification passed.[/green]')
    if expires_at is not None:
        rich.print(
            f'Server certificate valid until: {expires_at:%Y-%m-%d %H:%M:%S %Z}\n'
        )
    else:
        rich.print('Server certificate expiry is unavailable.\n')


async def main() -> None:
    """Check the config, TLS and live credentials before running integration tests."""
    config = load_config(TITLE)
    await asyncio.to_thread(check_tls)
    await fetch_author_posts(config, TITLE, limit=1)
    rich.print('[green]✅ Credentials are live - running the integration suite[/green]')


if __name__ == '__main__':
    asyncio.run(main())
