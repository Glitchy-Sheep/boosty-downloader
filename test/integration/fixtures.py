"""Shared fixtures for Boosty API integration tests."""

import logging
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from aiohttp import ClientSession
from aiohttp_retry import ExponentialRetry, RetryClient
from pydantic import ValidationError

from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.src.boosty_api.core.endpoints import BASE_URL
from integration.configuration import IntegrationTestConfig

logger = logging.getLogger(__name__)


@pytest.fixture(scope='session')
def integration_config() -> IntegrationTestConfig:
    """
    Provides configuration for integration tests.
    """
    try:
        return IntegrationTestConfig()  # pyright: ignore[reportCallIssue] : will be loaded automatically by pydantic_settings

    except ValidationError as e:
        logger.exception('❌ Failed to load integration test config:')
        for err in e.errors():
            loc = '.'.join(map(str, err['loc']))
            msg = err['msg']
            logger.exception(f'  - {loc}: {msg}')
        pytest.skip('Integration tests require valid configuration')


@pytest.fixture
def boosty_headers(integration_config: IntegrationTestConfig) -> dict[str, str]:
    """Returns headers with authorization token for Boosty API requests."""
    return {
        'Authorization': integration_config.boosty_auth_token,
        'Cookie': integration_config.boosty_cookies,
        'Content-Type': 'application/json',
    }


@pytest_asyncio.fixture
async def http_session(
    boosty_headers: dict[str, str],
) -> AsyncGenerator[ClientSession, None]:
    """Creates an HTTP session for making requests."""
    session = ClientSession(
        headers=boosty_headers,
        base_url=BASE_URL,
    )
    yield session
    await session.close()


@pytest_asyncio.fixture
async def retry_client(
    http_session: ClientSession,
) -> AsyncGenerator[RetryClient, None]:
    """Creates a retry client for handling transient failures."""
    retry_options = ExponentialRetry(attempts=3, start_timeout=1.0)
    client = RetryClient(
        client_session=http_session,
        retry_options=retry_options,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture
async def boosty_client(retry_client: RetryClient) -> BoostyAPIClient:
    """Creates a Boosty API client configured with authentication."""
    return BoostyAPIClient(session=retry_client)


@pytest_asyncio.fixture
async def unauthorized_retry_client(
    http_session: ClientSession,
) -> AsyncGenerator[RetryClient, None]:
    """Creates a retry client without authentication for testing unauthorized scenarios."""
    retry_options = ExponentialRetry(attempts=3, start_timeout=1.0)
    client = RetryClient(
        client_session=http_session,
        retry_options=retry_options,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture
async def unauthorized_boosty_client(
    unauthorized_retry_client: RetryClient,
) -> BoostyAPIClient:
    """Creates a Boosty API client without authentication for testing unauthorized scenarios."""
    return BoostyAPIClient(session=unauthorized_retry_client)
