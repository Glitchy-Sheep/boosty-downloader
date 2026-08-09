"""Preflight for `task test:api`: verify ./.env and live credentials before pytest."""

from __future__ import annotations

import asyncio

import rich
from _integration_env import fetch_author_posts, load_config

TITLE = 'test:api'


async def main() -> None:
    """Load the config and make one cheap live request; exit loudly when either fails."""
    config = load_config(TITLE)
    await fetch_author_posts(config, TITLE, limit=1)
    rich.print('[green]✅ Credentials are live - running the integration suite[/green]')


if __name__ == '__main__':
    asyncio.run(main())
