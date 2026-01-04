"""Defines the application environment and dependency injection context for resource management."""

from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

import aiohttp
from aiohttp.typedefs import LooseHeaders
from aiohttp_retry import RetryClient, RetryOptionsBase

from boosty_downloader.src.cli.console_progress_reporter import (
    ProgressReporter,
    use_reporter,
)
from boosty_downloader.src.infrastructure.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.src.infrastructure.loggers.logger_instances import RichLogger
from boosty_downloader.src.infrastructure.post_caching.post_cache import SQLitePostCache


class AppEnvironment:
    """Manages the application's resource initialization and cleanup, providing an async context for dependency injection."""

    @dataclass
    class Environment:
        """Holds initialized application resources for use within the app context."""

        boosty_api_client: BoostyAPIClient
        downloading_retry_client: RetryClient
        progress_reporter: ProgressReporter
        destination_directory: Path
        post_cache: SQLitePostCache

    @dataclass
    class AppConfig:
        """Configuration for the application environment."""

        author_name: str
        target_directory: Path
        boosty_headers: LooseHeaders
        boosty_cookies_jar: aiohttp.CookieJar
        retry_options: RetryOptionsBase
        request_delay_seconds: float
        logger: RichLogger

    def __init__(
        self,
        config: AppConfig,
    ) -> None:
        self.author_name = config.author_name
        self.target_directory = config.target_directory
        self.boosty_headers = config.boosty_headers
        self.boosty_cookies_jar = config.boosty_cookies_jar
        self.logger = config.logger
        self.retry_options = config.retry_options
        self._request_delay_seconds = config.request_delay_seconds

    async def __aenter__(self) -> 'Environment':
        """Enter the async context and initialize resources."""
        self._exit_stack = AsyncExitStack()
        await self._exit_stack.__aenter__()

        authorized_boosty_session = await self._exit_stack.enter_async_context(
            # Don't: set BASE_URL here, the BoostyAPIClient will handle it internally.
            # Why: this session will be used for both downloading and API requests with different bases.
            aiohttp.ClientSession(
                headers=self.boosty_headers,
                cookie_jar=self.boosty_cookies_jar,
                timeout=aiohttp.ClientTimeout(total=None),
                trust_env=True,
            )
        )

        progress_reporter = await self._exit_stack.enter_async_context(
            use_reporter(
                reporter=ProgressReporter(
                    logger=self.logger.logging_logger_obj,
                    console=self.logger.console,
                )
            )
        )

        authorized_retry_client = RetryClient(
            authorized_boosty_session, retry_options=self.retry_options
        )

        boosty_api_client = BoostyAPIClient(
            authorized_retry_client,
            request_delay_seconds=self._request_delay_seconds,
        )

        post_cache = SQLitePostCache(
            destination=self.target_directory / self.author_name,
            logger=self.logger,
        )
        post_cache.__enter__()  # sync context manager
        self._exit_stack.callback(post_cache.__exit__, None, None, None)

        return self.Environment(
            boosty_api_client=boosty_api_client,
            downloading_retry_client=authorized_retry_client,
            progress_reporter=progress_reporter,
            destination_directory=self.target_directory / self.author_name,
            post_cache=post_cache,
        )

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exit the async context and clean up resources"""
        await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
