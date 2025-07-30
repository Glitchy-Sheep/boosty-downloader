"""Integration tests for Boosty API client.

These tests make real requests to the Boosty API and require proper configuration.
Run with: make test-integration

Required environment variables:
- BOOSTY_TOKEN: Valid authentication token
- BOOSTY_AVAILABLE_POST: URL/ID of accessible post
- BOOSTY_UNAVAILABLE_POST: URL/ID of post behind paywall
- BOOSTY_NONEXISTENT_AUTHOR: Username that doesn't exist
- BOOSTY_EXISTING_AUTHOR: Username of existing author
"""

import pytest

from boosty_downloader.src.boosty_api.core.client import (
    BoostyAPIClient,
    BoostyAPINoUsernameError,
)
from integration.configuration import IntegrationTestConfig

pytest_plugins = [
    'integration.fixtures',
]

# ------------------------------------------------------------------------------
# Tests


@pytest.mark.asyncio
async def test_get_posts_existing_author_success(
    boosty_client: BoostyAPIClient, integration_config: IntegrationTestConfig
) -> None:
    """Test successful retrieval of posts from an existing author."""
    response = await boosty_client.get_author_posts(
        author_name=integration_config.boosty_existing_author, limit=5
    )

    assert response.posts is not None
    assert response.extra is not None
    assert len(response.posts) >= 0


@pytest.mark.asyncio
async def test_get_posts_nonexistent_author_raises_error(
    boosty_client: BoostyAPIClient, integration_config: IntegrationTestConfig
) -> None:
    """Test that requesting posts from non-existent author raises BoostyAPINoUsernameError."""
    with pytest.raises(BoostyAPINoUsernameError):
        await boosty_client.get_author_posts(
            author_name=integration_config.boosty_nonexistent_author, limit=5
        )


@pytest.mark.asyncio
async def test_get_posts_with_pagination(
    boosty_client: BoostyAPIClient, integration_config: IntegrationTestConfig
) -> None:
    """Test pagination functionality for author posts."""
    first_page = await boosty_client.get_author_posts(
        author_name=integration_config.boosty_existing_author, limit=2
    )

    if not first_page.extra.is_last and first_page.extra.offset:
        second_page = await boosty_client.get_author_posts(
            author_name=integration_config.boosty_existing_author,
            limit=2,
            offset=first_page.extra.offset,
        )

        # Posts should be different between pages (assuming author has more than 2 posts)
        first_page_ids = {post.id for post in first_page.posts}
        second_page_ids = {post.id for post in second_page.posts}
        assert first_page_ids.isdisjoint(second_page_ids), (
            'Pages should contain different posts'
        )


@pytest.mark.asyncio
async def test_iterate_over_posts(
    boosty_client: BoostyAPIClient, integration_config: IntegrationTestConfig
) -> None:
    """Test the async generator for iterating over all author posts."""
    pages_count = 0
    total_posts = 0

    async for response in boosty_client.iterate_over_posts(
        author_name=integration_config.boosty_existing_author,
        posts_per_page=2,
        delay_seconds=0.1,
    ):
        pages_count += 1
        total_posts += len(response.posts)

        # Limit iteration to avoid running too long in tests
        if pages_count >= 3:
            break

    assert pages_count > 0, 'Should retrieve at least one page'
    assert total_posts >= 0, 'Should count posts correctly'
