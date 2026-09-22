"""
Composition root: turns the config and the CLI options into a running app.

cli is the top layer, so this is the one place that knows every concrete
class. Use cases see the same objects only through the application ports.
"""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from http import HTTPStatus
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
from boosty_downloader.infrastructure.yaml_configuration.config import (
    DEFAULT_CONFIG_PATH,
    DownloadSettings,
    init_config,
    read_download_settings,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from aiohttp_retry import RetryOptionsBase

    from boosty_downloader.application.ports import PostCache
    from boosty_downloader.infrastructure.loggers.base import RichLogger


@dataclass(frozen=True, slots=True)
class AppSettings:
    """
    Resolved once from config.yaml and the CLI overrides on top of it.

    Plain values only: the aiohttp objects built from them need a running
    event loop, and sync commands (clean-cache) load settings without one.
    """

    author_name: str
    # <target>/<author>: where the posts of this creator land.
    destination_dir: Path
    # <cache or target>/<author>: where the post cache of this creator lives.
    cache_dir: Path
    auth_header: str
    cookie: str


def _cache_dir(
    paths: DownloadSettings,
    *,
    username: str,
    destination_directory: Path | None,
    cache_directory: Path | None,
) -> Path:
    """<cache or target>/<author>; a CLI directory wins over the config value."""
    target = destination_directory or paths.target_directory
    cache_root = cache_directory or paths.cache_directory
    return (cache_root or target).absolute() / username


def load_settings(
    *,
    username: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
    destination_directory: Path | None = None,
    cache_directory: Path | None = None,
) -> AppSettings:
    """Load the config file; a CLI directory wins over the config value."""
    config = init_config(config_path)
    paths = config.downloading_settings
    target = destination_directory or paths.target_directory
    return AppSettings(
        author_name=username,
        destination_dir=target.absolute() / username,
        cache_dir=_cache_dir(
            paths,
            username=username,
            destination_directory=destination_directory,
            cache_directory=cache_directory,
        ),
        auth_header=config.auth.auth_header,
        cookie=config.auth.cookie,
    )


def resolve_cache_dir(
    *,
    username: str,
    config_path: Path = DEFAULT_CONFIG_PATH,
    cache_directory: Path | None = None,
) -> Path:
    """Where the creator's cache lives; no credentials needed to find it."""
    return _cache_dir(
        read_download_settings(config_path),
        username=username,
        destination_directory=None,
        cache_directory=cache_directory,
    )


@dataclass(frozen=True, slots=True)
class App:
    """Live handles of a started app. Settings stay in AppSettings."""

    api: BoostyAPIClient
    # Session without credentials, for media downloads only.
    media_http: RetryClient
    cache: PostCache
    reporter: ConsoleProgressReporter


# Transport retries: connection errors, 5xx (aiohttp-retry's default) and
# 429 rate limiting. Waits 2, 4, 8, 16 seconds between the five attempts:
# a rate limiter needs real pauses, the default 0.1s ladder just hammers it.
# Failures of the response body and expired links are the post retrier's job.
DEFAULT_RETRY_OPTIONS = ExponentialRetry(
    attempts=5,
    start_timeout=1.0,
    statuses={HTTPStatus.TOO_MANY_REQUESTS},
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
                headers=parse_auth_header(settings.auth_header),
                cookie_jar=parse_session_cookie(settings.cookie),
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
