"""Application initialization: config loading, update check, and AppEnvironment setup."""

from __future__ import annotations

import asyncio
import importlib.metadata
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import aiohttp
from aiohttp_retry import ExponentialRetry

from boosty_downloader.src.application.di.app_environment import AppEnvironment
from boosty_downloader.src.infrastructure.boosty_api.utils.auth_parsers import (
    parse_auth_header,
    parse_session_cookie,
)
from boosty_downloader.src.infrastructure.loggers import logger_instances
from boosty_downloader.src.infrastructure.update_checker.pypi_checker import (
    CheckFailed,
    NoUpdate,
    UpdateAvailable,
    check_for_updates,
)
from boosty_downloader.src.infrastructure.yaml_configuration.config import init_config

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


def _check_and_log_updates() -> None:
    """Check PyPI for updates and log the result."""
    current_version = importlib.metadata.version('boosty-downloader')
    result = check_for_updates(current_version, 'boosty-downloader')
    match result:
        case UpdateAvailable():
            logger_instances.downloader_logger.warning(
                f'🔔 [bold green]Update available[/bold green]: {result.latest_version} (current: {result.current_version})'
            )
            logger_instances.downloader_logger.warning(
                'You can update with --> [bold]pip install -U boosty-downloader[/bold]'
            )
            logger_instances.downloader_logger.warning(
                'But first, please check the changelog for breaking changes\n'
            )
        case NoUpdate():
            logger_instances.downloader_logger.info(
                'You are using the latest boosty-downloader version.\n'
            )
        case CheckFailed():
            logger_instances.downloader_logger.error(
                'Failed to check for updates, please check it manually.\n'
            )


@asynccontextmanager
async def initialized_app(
    *,
    username: str,
    request_delay_seconds: float,
    destination_directory: Path | None = None,
    cache_directory: Path | None = None,
) -> AsyncIterator[AppEnvironment.Environment]:
    """Load config, check for updates, and yield an initialized AppEnvironment."""
    config = init_config()

    if destination_directory is not None:
        config.downloading_settings.target_directory = destination_directory

    if cache_directory is not None:
        config.downloading_settings.cache_directory = cache_directory

    retry_options = ExponentialRetry(
        attempts=5,
        exceptions={
            aiohttp.ClientConnectorError,
            aiohttp.ClientOSError,
            aiohttp.ServerDisconnectedError,
            aiohttp.ClientResponseError,
            aiohttp.ClientConnectionError,
        },
    )

    # to_thread: the PyPI request is blocking; the event loop stays free.
    await asyncio.to_thread(_check_and_log_updates)

    async with AppEnvironment(
        config=AppEnvironment.AppConfig(
            author_name=username,
            target_directory=config.downloading_settings.target_directory.absolute(),
            cache_directory=config.downloading_settings.cache_directory.absolute()
            if config.downloading_settings.cache_directory
            else None,
            boosty_headers=parse_auth_header(config.auth.auth_header),
            boosty_cookies_jar=parse_session_cookie(config.auth.cookie),
            retry_options=retry_options,
            request_delay_seconds=request_delay_seconds,
            logger=logger_instances.downloader_logger,
        )
    ) as app_env:
        yield app_env
