"""Main entrypoint of the app"""

import asyncio
from pathlib import Path

import aiohttp
import typer

from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.src.boosty_api.core.endpoints import BASE_URL
from boosty_downloader.src.boosty_api.utils.auth_parsers import (
    parse_auth_header,
    parse_session_cookie,
)
from boosty_downloader.src.configuration.config import config
from boosty_downloader.src.download_manager.download_manager import (
    BoostyDownloadManager,
)
from boosty_downloader.src.download_manager.download_manager_config import (
    GeneralOptions,
    LoggerDependencies,
    NetworkDependencies,
)
from boosty_downloader.src.download_manager.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.src.loggers.failed_downloads_logger import FailedDownloadsLogger
from boosty_downloader.src.loggers.logger_instances import downloader_logger


async def main(
    username: str,
) -> None:
    """Download all posts from the specified user"""
    cookie_string = config.auth.cookie
    auth_header = config.auth.auth_header

    async with aiohttp.ClientSession(
        base_url=BASE_URL,
        headers=await parse_auth_header(auth_header),
        cookie_jar=await parse_session_cookie(cookie_string),
    ) as session:
        destionation_directory = Path('./boosty-downloads').absolute()
        boosty_api_client = BoostyAPIClient(session)

        async with aiohttp.ClientSession(
            # Don't use BASE_URL here (for other domains)
            # NOTE: Maybe should be refactored somehow to use same session
            headers=session.headers,
            cookie_jar=session.cookie_jar,
        ) as direct_session:
            downloader = BoostyDownloadManager(
                general_options=GeneralOptions(
                    target_directory=destionation_directory,
                ),
                network_dependencies=NetworkDependencies(
                    session=direct_session,
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

            await downloader.download_all_posts(username)


def main_wrapper(
    username: str = typer.Option(),
) -> None:
    """Wrap main function because typer can't run async functions directly"""
    asyncio.run(main(username))


if __name__ == '__main__':
    typer.run(main_wrapper)
