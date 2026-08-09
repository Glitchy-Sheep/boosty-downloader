"""Dev helper: dump posts JSON for the author configured in ./.env."""

from __future__ import annotations

import asyncio

import rich
from _integration_env import fetch_author_posts, load_config

TITLE = 'posts-example'


async def main() -> None:
    """Load the .env config, fetch posts of the configured author, print JSON."""
    config = load_config(TITLE)
    rich.print_json(data=await fetch_author_posts(config, TITLE, limit=10))


if __name__ == '__main__':
    asyncio.run(main())
