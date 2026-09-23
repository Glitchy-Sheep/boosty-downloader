"""
Canary: does the client still understand the live Boosty API?

CI runs this once a week without credentials against the public blog named
by CANARY_AUTHOR (see .github/workflows/canary.yaml). A red run means the
API changed under us: a post no longer parses, or the open posts stopped
carrying content. The workflow turns the red run into an issue. Additions
that break nothing, like a new key or chunk kind, are not failures here:
`task api:changes` lists them for the weekly report.

The suite sits outside pytest's testpaths on purpose: it needs the network.
Run it by hand with `CANARY_AUTHOR=<blog> task test:canary`.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import aiohttp
import pytest
import pytest_asyncio
from aiohttp_retry import RetryClient

from boosty_downloader.cli.composition_root import DEFAULT_RETRY_OPTIONS
from boosty_downloader.infrastructure.boosty_api.core.client import (
    MAX_POSTS_PER_PAGE,
    BoostyAPIClient,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from boosty_downloader.infrastructure.boosty_api.models.post.posts_request import (
        PostsResponse,
    )

AUTHOR_ENV = 'CANARY_AUTHOR'


@pytest.fixture(scope='session')
def canary_author() -> str:
    author = os.environ.get(AUTHOR_ENV, '')
    if not author:
        pytest.fail(
            f'{AUTHOR_ENV} is not set: name a public blog with at least one free post'
        )
    return author


@pytest_asyncio.fixture
async def public_client() -> AsyncGenerator[BoostyAPIClient]:
    """A client with no credentials: the probe must see what a stranger sees."""
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.DummyCookieJar(),
        timeout=aiohttp.ClientTimeout(total=60),
    ) as session:
        yield BoostyAPIClient(RetryClient(session, retry_options=DEFAULT_RETRY_OPTIONS))


@pytest_asyncio.fixture
async def first_page(
    public_client: BoostyAPIClient, canary_author: str
) -> PostsResponse:
    """One request: the newest posts of the blog, as many as the API gives at once."""
    return await public_client.get_author_posts(canary_author, limit=MAX_POSTS_PER_PAGE)


def test_every_post_parses(first_page: PostsResponse) -> None:
    """A post the client cannot parse means a field changed shape or went missing."""
    broken = [
        f'{post.title!r} ({post.post_id}): {post.errors}'
        for post in first_page.skipped_posts
    ]
    assert not broken, 'Posts the client could not parse:\n' + '\n'.join(broken)


def test_open_posts_carry_content(first_page: PostsResponse) -> None:
    """Without an open post with chunks the other checks prove nothing: the blog must have one."""
    assert any(post.has_access and post.data for post in first_page.posts), (
        f'No open post with content among the first {len(first_page.posts)} posts: '
        f'{AUTHOR_ENV} must name a blog with at least one free post that has content'
    )
