"""Preflight for `task test:api`: verify ./.env and live credentials before pytest."""

from __future__ import annotations

import asyncio

import rich
from _integration_env import fetch_author_posts, load_config

TITLE = 'test:api'


import ssl
import socket
from datetime import datetime

async def main() -> None:
    """Load the config and make one cheap live request; exit loudly when either fails."""
    config = load_config(TITLE)

    # Diagnose SSL issues before making the request
    try:
        # Get the peer certificate to check its validity
        ctx = ssl.create_default_context()
        with socket.create_connection(('api.boosty.to', 443), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname='api.boosty.to') as ssock:
                cert = ssock.getpeercert()
                not_after = datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
                if not_after < datetime.now():
                    rich.print('[red]❌ Certificate for api.boosty.to expired at {}[/red]'.format(not_after))
                else:
                    rich.print('[yellow]⚠️ Certificate valid until {}. Proceeding.[/yellow]'.format(not_after))
    except Exception as e:
        rich.print('[red]❌ SSL diagnostic failed: {}[/red]'.format(e))
        raise

    await fetch_author_posts(config, TITLE, limit=1)
    rich.print('[green]✅ Credentials are live - running the integration suite[/green]')


if __name__ == '__main__':
    asyncio.run(main())
