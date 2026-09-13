"""
Composition root: turns the config and the CLI options into a running app.

cli is the top layer, so this is the one place that knows every concrete
class. Use cases see the same objects only through the application ports.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp
from aiohttp_retry import ExponentialRetry, RetryClient

from boosty_downloader.cli.console_progress_reporter import (
    ConsoleProgressReporter,
    use_reporter,
)
from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.infrastructure.boosty_api.utils.auth_parsers import (
    parse_auth_header,
    parse_session_cookie,
)
from boosty_downloader.infrastructure.loggers.request_tracing import (
    create_request_trace_config,
)
from boosty_downloader.infrastructure.post_caching.post_cache import SQLitePostCache
from boosty_downloader.infrastructure.yaml_configuration.config import init_config

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from aiohttp.typedefs import LooseHeaders
    from aiohttp_retry import RetryOptionsBase

    from boosty_downloader.application.ports import PostCache
    from boosty_downloader.infrastructure.loggers.base import RichLogger


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Resolved once from config.yaml and the CLI overrides on top of it."""

    author_name: str
    # <target>/<author>: where the posts of this creator land.
    destination_dir: Path
    # <cache or target>/<author>: where the post cache of this creator lives.
    cache_dir: Path
    boosty_headers: LooseHeaders
    boosty_cookies: aiohttp.CookieJar


def load_settings(
    *,
    username: str,
    destination_directory: Path | None = None,
    cache_directory: Path | None = None,
) -> AppSettings:
    """Load config.yaml; a CLI directory wins over the config value."""
    config = init_config()
    target = destination_directory or config.downloading_settings.target_directory
    cache_root = cache_directory or config.downloading_settings.cache_directory
    return AppSettings(
        author_name=username,
        destination_dir=target.absolute() / username,
        cache_dir=(cache_root or target).absolute() / username,
        boosty_headers=parse_auth_header(config.auth.auth_header),
        boosty_cookies=parse_session_cookie(config.auth.cookie),
    )


@dataclass(frozen=True, slots=True)
class App:
    """Live handles of a started app. Settings stay in AppSettings."""

    api: BoostyAPIClient
    # Session without credentials, for media downloads only.
    media_http: RetryClient
    cache: PostCache
    reporter: ConsoleProgressReporter


DEFAULT_RETRY_OPTIONS = ExponentialRetry(
    attempts=5,
    exceptions={
        aiohttp.ClientConnectorError,
        aiohttp.ClientOSError,
        aiohttp.ServerDisconnectedError,
        aiohttp.ClientResponseError,
        aiohttp.ClientConnectionError,
    },
)

# No limit on the whole download: big videos legally take hours.
# Limits are on silence only - a dead connection must surface as an
# error, not as an eternal hang:
# - connect: a healthy server answers in under a second
# - sock_read: max quiet time between received chunks
_NETWORK_TIMEOUT = aiohttp.ClientTimeout(total=None, connect=30, sock_read=90)


@asynccontextmanager
async def open_app(
    settings: AppSettings,
    *,
    request_delay_seconds: float,
    logger: RichLogger,
    retry_options: RetryOptionsBase = DEFAULT_RETRY_OPTIONS,
) -> AsyncGenerator[App]:
    """Open the sessions, the reporter and the cache; close them all on exit."""
    async with AsyncExitStack() as stack:
        api_session = await stack.enter_async_context(
            # Credentials live ONLY here: this session talks to the Boosty API.
            aiohttp.ClientSession(
                headers=settings.boosty_headers,
                cookie_jar=settings.boosty_cookies,
                timeout=_NETWORK_TIMEOUT,
                trust_env=True,
                trace_configs=[
                    create_request_trace_config(total_attempts=retry_options.attempts)
                ],
            )
        )
        media_session = await stack.enter_async_context(
            # Media downloads carry no credentials: access to protected files
            # comes from the signed query inside the url. The account token
            # must not travel to CDN and third-party video hosts.
            aiohttp.ClientSession(
                cookie_jar=aiohttp.DummyCookieJar(),
                timeout=_NETWORK_TIMEOUT,
                trust_env=True,
                trace_configs=[
                    create_request_trace_config(total_attempts=retry_options.attempts)
                ],
            )
        )
        reporter = await stack.enter_async_context(
            use_reporter(
                ConsoleProgressReporter(
                    logger=logger.logging_logger_obj, console=logger.console
                )
            )
        )
        cache = stack.enter_context(
            SQLitePostCache(destination=settings.cache_dir, logger=logger)
        )
        yield App(
            api=BoostyAPIClient(
                RetryClient(api_session, retry_options=retry_options),
                request_delay_seconds=request_delay_seconds,
            ),
            media_http=RetryClient(media_session, retry_options=retry_options),
            cache=cache,
            reporter=reporter,
        )
