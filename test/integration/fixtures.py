"""Shared fixtures for Boosty API integration tests."""

import logging
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from aiohttp import ClientSession
from aiohttp.typedefs import LooseHeaders
from aiohttp_retry import ExponentialRetry, RetryClient
from pydantic import ValidationError

from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.src.boosty_api.core.endpoints import BASE_URL
from integration.configuration import IntegrationTestConfig

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------------------
# Utilities for further fixtures


@pytest.fixture(scope='session')
def integration_config() -> IntegrationTestConfig:
    """
    Provides configuration for integration tests.

    It loads the configuration from the environment or a configuration file.
    If the configuration is invalid, it logs the errors and skips the tests.
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
def boosty_headers(integration_config: IntegrationTestConfig) -> LooseHeaders:
    """Returns headers with authorization token for Boosty API requests."""
    return {
        'Authorization': integration_config.boosty_auth_token,
        'Cookie': integration_config.boosty_cookies,
        'Content-Type': 'application/json',
    }


# ------------------------------------------------------------------------------
# Different session setups


@pytest_asyncio.fixture
async def authorized_http_session(
    boosty_headers: LooseHeaders,
) -> AsyncGenerator[ClientSession, None]:
    """Creates an HTTP session for making requests."""
    session = ClientSession(
        headers=boosty_headers,
        base_url=BASE_URL,
    )
    yield session
    await session.close()


@pytest_asyncio.fixture
async def unauthorized_http_session() -> AsyncGenerator[ClientSession, None]:
    """Creates an HTTP session without authorization headers."""
    session = ClientSession(base_url=BASE_URL)
    yield session
    await session.close()


@pytest_asyncio.fixture
async def invalid_auth_http_session() -> AsyncGenerator[ClientSession, None]:
    session = ClientSession(
        headers={
            'Authorization': 'Bearer '
            + 'a' * 64,  # Looks valid (64 hex chars), but not actually valid
        },
        base_url=BASE_URL,
    )
    yield session
    await session.close()


# ------------------------------------------------------------------------------
# Clients for Boosty API


@pytest_asyncio.fixture
async def authorized_retry_client(
    authorized_http_session: ClientSession,
) -> AsyncGenerator[RetryClient, None]:
    """Creates a retry client for handling transient failures."""
    retry_options = ExponentialRetry(attempts=3, start_timeout=1.0)
    client = RetryClient(
        client_session=authorized_http_session,
        retry_options=retry_options,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture
async def unauthorized_retry_client(
    unauthorized_http_session: ClientSession,
) -> AsyncGenerator[RetryClient, None]:
    """Creates a retry client without authentication for testing unauthorized scenarios."""
    retry_options = ExponentialRetry(attempts=3, start_timeout=1.0)
    client = RetryClient(
        client_session=unauthorized_http_session,
        retry_options=retry_options,
    )
    yield client
    await client.close()


@pytest_asyncio.fixture
async def invalid_auth_retry_client(
    invalid_auth_http_session: ClientSession,
) -> AsyncGenerator[RetryClient, None]:
    """Creates a retry client with invalid authentication for testing error handling."""
    retry_options = ExponentialRetry(attempts=3, start_timeout=1.0)
    client = RetryClient(
        client_session=invalid_auth_http_session,
        retry_options=retry_options,
    )
    yield client
    await client.close()


# ------------------------------------------------------------------------------
# Clients for Boosty API


@pytest_asyncio.fixture
async def authorized_boosty_client(
    authorized_retry_client: RetryClient,
) -> BoostyAPIClient:
    """Creates a Boosty API client configured with authentication."""
    return BoostyAPIClient(session=authorized_retry_client)


@pytest_asyncio.fixture
async def unauthorized_boosty_client(
    unauthorized_retry_client: RetryClient,
) -> BoostyAPIClient:
    """Creates a Boosty API client without authentication for testing unauthorized scenarios."""
    return BoostyAPIClient(session=unauthorized_retry_client)


@pytest_asyncio.fixture
async def invalid_auth_boosty_client(
    invalid_auth_retry_client: RetryClient,
) -> BoostyAPIClient:
    """Creates a Boosty API client with invalid authentication for testing error handling."""
    return BoostyAPIClient(session=invalid_auth_retry_client)
