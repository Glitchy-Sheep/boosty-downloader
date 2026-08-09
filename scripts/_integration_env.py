"""Shared plumbing for dev scripts that talk to the live Boosty API using ./.env."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, NoReturn, cast

import aiohttp
import rich
from pydantic import ValidationError
from rich.panel import Panel

sys.path.insert(0, str(Path(__file__).parent.parent / 'test'))

from integration.configuration import IntegrationTestConfig

from boosty_downloader.src.infrastructure.boosty_api.core.endpoints import (
    BOOSTY_DEFAULT_BASE_URL,
)

CREDENTIALS_HINT = (
    'Refresh BOOSTY_TOKEN and BOOSTY_COOKIES in ./.env -\n'
    'get fresh values with: [bold]boosty-downloader show-auth-script[/bold]'
)


def fail(title: str, message: str) -> NoReturn:
    """Print a red panel with the problem and the fix, then exit with an error."""
    rich.print(Panel(message, title=title, border_style='red'))
    sys.exit(1)


def load_config(title: str) -> IntegrationTestConfig:
    """Load ./.env; when it is missing or incomplete, exit naming the keys to fill."""
    try:
        return IntegrationTestConfig()  # pyright: ignore[reportCallIssue] : loaded from ./.env by pydantic_settings
    except ValidationError as error:
        broken_keys = ', '.join(str(err['loc'][0]) for err in error.errors())
        fail(
            title,
            f'./.env is missing or incomplete, check: [bold]{broken_keys}[/bold]\n'
            'Copy .env.example to ./.env and fill in the values.\n' + CREDENTIALS_HINT,
        )


async def fetch_author_posts(
    config: IntegrationTestConfig,
    title: str,
    limit: int,
) -> dict[str, Any]:
    """Fetch a posts page; exit with a refresh hint when Boosty rejects the creds."""
    endpoint = f'{BOOSTY_DEFAULT_BASE_URL}blog/{config.boosty_existing_author}/post/'
    headers = {'Authorization': config.boosty_auth_token.get_secret_value()}
    timeout = aiohttp.ClientTimeout(total=30)

    try:
        async with (
            aiohttp.ClientSession(headers=headers, timeout=timeout) as session,
            session.get(endpoint, params={'limit': limit}) as response,
        ):
            posts_data = await response.json()
    except aiohttp.ClientError as error:
        fail(
            title,
            f'Could not reach Boosty: {error}\nCheck your network and try again.',
        )

    if not isinstance(posts_data, dict):
        fail(title, f'Unexpected Boosty response: {posts_data!r}')
    data = cast('dict[str, Any]', posts_data)

    if 'error' in data:
        reason = data.get('error_description', data['error'])
        fail(
            title,
            f'Boosty rejected the request: [bold]{reason}[/bold]\n\n'
            + CREDENTIALS_HINT,
        )

    return data
