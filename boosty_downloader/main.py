"""Main entrypoint of the app"""

from __future__ import annotations

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
    DownloadContentTypeFilter,
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

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode='rich',
)


async def main(
    *,
    username: str,
    post_url: str | None,
    check_total_count: bool,
    clean_cache: bool,
    content_type_filter: list[DownloadContentTypeFilter],
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
                    download_content_type_filter=content_type_filter,
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

            if post_url is not None:
                await downloader.download_post_by_url(username, post_url)
                return

            await downloader.download_all_posts(username)


@app.command()
def main_wrapper(
    *,
    username: Annotated[
        str,
        typer.Option(),
    ],
    post_url: Annotated[
        str | None,
        typer.Option(
            '--post-url',
            '-p',
            help='Download only the specified post if possible',
        ),
    ] = None,
    content_type_filter: Annotated[
        list[DownloadContentTypeFilter] | None,
        typer.Option(
            '--content-type-filter',
            '-f',
            help='Filter the download by content type [[bold]files, post_content, boosty_videos, external_videos[/bold]]',
        ),
    ] = None,
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
    """
    CLI Tool to download posts from Boosty by author username.

    You can use the --post-url option to download only the specified post.
    Otherwise all posts will be downloaded from the newest to the oldest.

    [bold green]If you want only specific content you can use filters like this:[/bold green]

    [bold]This will download only files and post content[/bold]:

        [italic]boosty-downloader --username -f files -f post_content[/italic]
    """
    asyncio.run(
        main(
            username=username,
            check_total_count=check_total_count,
            clean_cache=clean_cache,
            post_url=post_url,
            content_type_filter=content_type_filter
            if content_type_filter
            else list(DownloadContentTypeFilter),
        ),
    )


def bootstrap() -> None:
    """
    Run main entry point of the whole app.

    This run typer CLI using app() config.

    It doesn't run the app directly, but through main_wrapper,
    because main app by itself is async and can't be run directly with typer.
    """
    app()


if __name__ == '__main__':
    bootstrap()
