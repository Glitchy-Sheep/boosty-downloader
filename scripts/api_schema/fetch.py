"""
Live answers of the Boosty API, kept in memory only.

The account token is sent when one is found (`BOOSTY_TOKEN` or the app's
config.yaml), so locked posts of the blogs the account can read show their
shape too. Nothing is written to disk here: the caller turns the answers
into shapes and drops them.
"""

from __future__ import annotations

import os
from http import HTTPStatus
from typing import TYPE_CHECKING, cast

import aiohttp
import yaml
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from pathlib import Path

from boosty_downloader.infrastructure.boosty_api.core.client import MAX_POSTS_PER_PAGE
from boosty_downloader.infrastructure.boosty_api.core.endpoints import (
    BOOSTY_DEFAULT_BASE_URL,
)

JsonDict = dict[str, object]


class _EnvToken(BaseSettings):
    """`BOOSTY_TOKEN` from the environment or ./.env; other keys are ignored."""

    boosty_auth_token: SecretStr | None = Field(None, alias='BOOSTY_TOKEN')

    model_config = SettingsConfigDict(env_file='.env', extra='ignore')


class FetchError(Exception):
    """The API answered, but not with a page: the message says what to fix."""


def load_token(config_path: Path) -> str | None:
    """
    Find the Authorization value, or None for an anonymous run.

    In order: `BOOSTY_TOKEN` in the environment, `auth.auth_header` of the
    app config, `BOOSTY_TOKEN` in ./.env. The config comes before the dotenv
    file because the app keeps it fresh; the dotenv file serves the
    integration tests and goes stale unnoticed.
    """
    env_token = os.environ.get('BOOSTY_TOKEN')
    if env_token:
        return env_token
    config_header = _config_header(config_path)
    if config_header:
        return config_header
    dotenv_token = _EnvToken().boosty_auth_token  # pyright: ignore[reportCallIssue] : loaded from ./.env
    return dotenv_token.get_secret_value() if dotenv_token is not None else None


def _config_header(config_path: Path) -> str | None:
    if not config_path.is_file():
        return None
    config = cast('object', yaml.safe_load(config_path.read_text(encoding='utf-8')))
    if not isinstance(config, dict):
        return None
    auth = cast('dict[str, object]', config).get('auth')
    if not isinstance(auth, dict):
        return None
    header = cast('dict[str, object]', auth).get('auth_header')
    return header if isinstance(header, str) and header else None


def open_session(token: str | None) -> aiohttp.ClientSession:
    """Open a session with the token as the only header; no cookies are kept."""
    headers = {'Authorization': token} if token else {}
    return aiohttp.ClientSession(
        headers=headers,
        cookie_jar=aiohttp.DummyCookieJar(),
        timeout=aiohttp.ClientTimeout(total=60),
    )


async def fetch_pages(
    session: aiohttp.ClientSession, blog: str, *, pages: int
) -> list[JsonDict]:
    """Up to `pages` listing answers of a blog, newest first, as decoded JSON."""
    answers: list[JsonDict] = []
    offset: str | None = None
    for _ in range(pages):
        params = {'limit': str(MAX_POSTS_PER_PAGE)}
        if offset:
            params['offset'] = offset
        page = await _get(session, f'blog/{blog}/post/', params, what=f'blog {blog}')
        answers.append(page)
        extra = cast('JsonDict', page.get('extra', {}))
        offset = cast('str | None', extra.get('offset'))
        if extra.get('isLast') or not offset:
            break
    return answers


async def fetch_post(
    session: aiohttp.ClientSession, blog: str, post_id: str
) -> JsonDict:
    """One post through the single-post endpoint."""
    return await _get(session, f'blog/{blog}/post/{post_id}', {}, what='the post')


async def _get(
    session: aiohttp.ClientSession, endpoint: str, params: dict[str, str], *, what: str
) -> JsonDict:
    async with session.get(
        BOOSTY_DEFAULT_BASE_URL + endpoint, params=params
    ) as response:
        if response.status == HTTPStatus.NOT_FOUND:
            message = f'{what}: not found (404)'
            raise FetchError(message)
        if response.status == HTTPStatus.UNAUTHORIZED:
            message = 'Credentials rejected (401): refresh BOOSTY_TOKEN in ./.env'
            raise FetchError(message)
        if response.status != HTTPStatus.OK:
            message = f'{what}: unexpected status {response.status}'
            raise FetchError(message)
        return cast('JsonDict', await response.json())
