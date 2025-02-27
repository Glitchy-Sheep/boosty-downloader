"""Main entrypoint of the app"""

import asyncio
from pathlib import Path
from typing import Annotated

import aiohttp
import typer
from aiohttp_retry import ExponentialRetry, RetryClient

from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.src.boosty_api.core.endpoints import BASE_URL
from boosty_downloader.src.boosty_api.utils.auth_parsers import (
    parse_auth_header,
    parse_session_cookie,
)
from boosty_downloader.src.download_manager.download_manager import (
    BoostyDownloadManager,
)
from boosty_downloader.src.download_manager.download_manager_config import (
    GeneralOptions,
    LoggerDependencies,
    NetworkDependencies,
)
from boosty_downloader.src.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.src.loggers.failed_downloads_logger import FailedDownloadsLogger
from boosty_downloader.src.loggers.logger_instances import downloader_logger
from boosty_downloader.src.yaml_configuration.config import config


async def main(
    *,
    username: str,
    check_total_count: bool,
    clean_cache: bool,
) -> None:
    """Download all posts from the specified user"""
    cookie_string = config.auth.cookie
    auth_header = config.auth.auth_header

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

    async with aiohttp.ClientSession(
        base_url=BASE_URL,
        headers=await parse_auth_header(auth_header),
        cookie_jar=await parse_session_cookie(cookie_string),
    ) as session:
        destionation_directory = Path('./boosty-downloads').absolute()
        boosty_api_client = BoostyAPIClient(
            RetryClient(session, retry_options=retry_options),
        )

        async with aiohttp.ClientSession(
            # Don't use BASE_URL here (for other domains)
            # NOTE: Maybe should be refactored somehow to use same session
            headers=session.headers,
            cookie_jar=session.cookie_jar,
            timeout=aiohttp.ClientTimeout(total=None),
            trust_env=True,
        ) as direct_session:
            retry_client = RetryClient(
                direct_session,
                retry_options=retry_options,
            )

            downloader = BoostyDownloadManager(
                general_options=GeneralOptions(
                    target_directory=destionation_directory,
                ),
                network_dependencies=NetworkDependencies(
                    session=retry_client,
                    api_client=boosty_api_client,
                    external_videos_downloader=ExternalVideosDownloader(),
                ),
                logger_dependencies=LoggerDependencies(
                    logger=downloader_logger,
                    failed_downloads_logger=FailedDownloadsLogger(
                        file_path=destionation_directory
                        / username
                        / 'failed_downloads.txt',
                    ),
                ),
            )

            if check_total_count:
                await downloader.only_check_total_posts(username)
                return

            if clean_cache:
                await downloader.clean_cache(username)
                return

            await downloader.download_all_posts(username)


def main_wrapper(
    *,
    username: Annotated[
        str,
        typer.Option(),
    ],
    check_total_count: Annotated[
        bool,
        typer.Option(
            '--total-post-check',
            '-t',
            help='Check total count of posts and exit, no download',
        ),
    ] = False,
    clean_cache: Annotated[
        bool,
        typer.Option(
            '--clean-cache',
            '-c',
            help='Remove posts cache for selected username, so all posts will be redownloaded',
        ),
    ] = False,
) -> None:
    """Wrap main function because typer can't run async functions directly"""
    asyncio.run(
        main(
            username=username,
            check_total_count=check_total_count,
            clean_cache=clean_cache,
        ),
    )


if __name__ == '__main__':
    typer.run(main_wrapper)
