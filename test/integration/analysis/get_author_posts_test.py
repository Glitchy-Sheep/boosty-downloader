import pytest
import rich
from aiohttp_retry import RetryClient

from boosty_downloader.src.boosty_api.utils.filter_none_params import filter_none_params
from integration.fixtures import IntegrationTestConfig

pytest_plugins = [
    'integration.fixtures',
]

@pytest.mark.asyncio
async def test_get_author_posts(retry_client: RetryClient, integration_config: IntegrationTestConfig) -> None:
    """Test successful retrieval of posts from an existing author."""
    endpoint = f'blog/{integration_config.boosty_existing_author}/post/'

    posts_raw = await retry_client.get(
        endpoint,
        params=filter_none_params(
            {
                'limit': 1,
            },
        ),
    )
    posts_data = await posts_raw.json()

    assert posts_data is not None

    rich.print_json(data=posts_data)
