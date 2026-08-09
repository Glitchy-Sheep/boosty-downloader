"""Integration tests for Boosty API client.

These tests make real requests to the Boosty API and require proper configuration.

Please see test/ABOUT_TESTING.md for more details.
"""

import pytest

from boosty_downloader.src.infrastructure.boosty_api import (
    BoostyAPIClient,
)
from boosty_downloader.src.infrastructure.boosty_api.core.client import (
    BoostyAPINoUsernameError,
    BoostyAPIUnauthorizedError,
)
from integration.configuration import IntegrationTestConfig

# For automatic fixture discovery
pytest_plugins = [
    'integration.fixtures',
]


@pytest.mark.asyncio
async def test_get_posts_existing_author_success(
    authorized_boosty_client: BoostyAPIClient, integration_config: IntegrationTestConfig
) -> None:
    """The configured author must yield a non-empty, parsed page of posts."""
    response = await authorized_boosty_client.get_author_posts(
        author_name=integration_config.boosty_existing_author, limit=5
    )

    assert response.posts, (
        f'No posts for "{integration_config.boosty_existing_author}" - '
        'BOOSTY_EXISTING_AUTHOR in ./.env must name an author with public posts'
    )


@pytest.mark.asyncio
async def test_get_posts_nonexistent_author_raises_error(
    authorized_boosty_client: BoostyAPIClient, integration_config: IntegrationTestConfig
) -> None:
    """A wrong username must raise BoostyAPINoUsernameError - it powers the "author not found" message."""
    with pytest.raises(BoostyAPINoUsernameError):
        await authorized_boosty_client.get_author_posts(
            author_name=integration_config.boosty_nonexistent_author, limit=5
        )


@pytest.mark.asyncio
async def test_get_posts_with_pagination(
    authorized_boosty_client: BoostyAPIClient, integration_config: IntegrationTestConfig
) -> None:
    """Two consecutive pages must contain different posts - else a full download would fetch duplicates."""
    first_page = await authorized_boosty_client.get_author_posts(
        author_name=integration_config.boosty_existing_author, limit=2
    )

    if first_page.extra.is_last or not first_page.extra.offset:
        pytest.skip(
            f'"{integration_config.boosty_existing_author}" fits in one page - '
            'pagination needs an author with 3+ posts to compare pages'
        )

    second_page = await authorized_boosty_client.get_author_posts(
        author_name=integration_config.boosty_existing_author,
        limit=2,
        offset=first_page.extra.offset,
    )

    first_page_ids = {post.id for post in first_page.posts}
    second_page_ids = {post.id for post in second_page.posts}
    assert first_page_ids.isdisjoint(second_page_ids), (
        'Both pages returned the same posts - offset pagination is broken'
    )


@pytest.mark.asyncio
async def test_iterate_over_posts(
    authorized_boosty_client: BoostyAPIClient, integration_config: IntegrationTestConfig
) -> None:
    """The pagination generator must yield pages with posts for an author who has them."""
    pages_count = 0
    total_posts = 0

    async for response in authorized_boosty_client.iterate_over_posts(
        author_name=integration_config.boosty_existing_author,
        posts_per_page=2,
    ):
        pages_count += 1
        total_posts += len(response.posts)

        # Limit iteration to avoid running too long in tests
        if pages_count >= 3:
            break

    assert pages_count > 0, 'The generator yielded no pages at all'
    assert total_posts > 0, (
        'The generator yielded pages but zero posts - page parsing inside iteration is broken'
    )


@pytest.mark.asyncio
async def test_invalid_token_raises_unauthorized_error(
    invalid_auth_boosty_client: BoostyAPIClient,
    integration_config: IntegrationTestConfig,
) -> None:
    """A stale/wrong token must raise BoostyAPIUnauthorizedError - it powers the "refresh your token" message."""
    with pytest.raises(BoostyAPIUnauthorizedError):
        await invalid_auth_boosty_client.get_author_posts(
            author_name=integration_config.boosty_existing_author, limit=5
        )
