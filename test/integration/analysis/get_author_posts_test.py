from typing import Any

import pytest
import rich
from aiohttp_retry import RetryClient

from boosty_downloader.src.infrastructure.boosty_api.utils.filter_none_params import (
    filter_none_params,
)
from integration.configuration import IntegrationTestConfig

pytest_plugins = [
    'integration.fixtures',
]


@pytest.mark.asyncio
async def test_get_author_posts(
    authorized_retry_client: RetryClient, integration_config: IntegrationTestConfig
) -> None:
    """Test successful retrieval of posts from an existing author."""
    endpoint = f'blog/{integration_config.boosty_existing_author}/post/'

    posts_raw = await authorized_retry_client.get(
        endpoint,
        params=filter_none_params(
            {
                'limit': 10,
            },
        ),
    )
    posts_data = await posts_raw.json()

    assert posts_data is not None

    rich.print_json(data=posts_data)


@pytest.mark.asyncio
async def test_all_data_chunk_types(
    authorized_retry_client: RetryClient,
    integration_config: IntegrationTestConfig,
) -> None:
    """Test successful retrieval of posts from an existing author."""
    endpoint = f'blog/{integration_config.boosty_existing_author}/post/'

    posts_raw = await authorized_retry_client.get(
        endpoint,
        params=filter_none_params(
            {
                'limit': 25,
            },
        ),
    )
    posts_data = await posts_raw.json()

    assert posts_data is not None

    unique_data_types: Any = {}

    for post in posts_data['data']:
        rich.print(post)
        for chunk in post['data']:
            if chunk['type'] not in unique_data_types:
                unique_data_types[chunk['type']] = chunk

    rich.print_json(data=unique_data_types)
