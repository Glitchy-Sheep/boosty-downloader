"""Main entrypoint of the app"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import aiohttp
import typer
from aiohttp_retry import ExponentialRetry, RetryClient
from sqlalchemy.exc import DatabaseError, IntegrityError, OperationalError

from boosty_downloader.src.application.download_manager.download_manager import (
    BoostyDownloadManager,
)
from boosty_downloader.src.application.download_manager.download_manager_config import (
    GeneralOptions,
    LoggerDependencies,
    NetworkDependencies,
    VideoQualityOption,
)
from boosty_downloader.src.application.filtering import (
    DownloadContentTypeFilter,
)
from boosty_downloader.src.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.src.infrastructure.boosty_api.core.client import (
    BoostyAPIClient,
    BoostyAPINoUsernameError,
    BoostyAPIUnauthorizedError,
    BoostyAPIUnknownError,
    BoostyAPIValidationError,
)
from boosty_downloader.src.infrastructure.boosty_api.core.endpoints import BASE_URL
from boosty_downloader.src.infrastructure.boosty_api.utils.auth_parsers import (
    parse_auth_header,
    parse_session_cookie,
)
from boosty_downloader.src.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.src.infrastructure.loggers import logger_instances
from boosty_downloader.src.infrastructure.loggers.failed_downloads_logger import (
    FailedDownloadsLogger,
)
from boosty_downloader.src.infrastructure.loggers.logger_instances import (
    downloader_logger,
)
from boosty_downloader.src.infrastructure.post_caching.post_cache import SQLitePostCache
from boosty_downloader.src.infrastructure.yaml_configuration.config import init_config
from boosty_downloader.src.interfaces.console_progress_reporter import (
    ProgressReporter,
    use_reporter,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode='rich',
)

GITHUB_ISSUES_URL = 'https://github.com/Glitchy-Sheep/boosty-downloader/issues'


async def main(  # noqa: PLR0913 (too many arguments because of typer)
    *,
    username: str,
    post_url: str | None,
    check_total_count: bool,
    clean_cache: bool,
    content_type_filter: list[DownloadContentTypeFilter],
    preferred_video_quality: VideoQualityOption,
    request_delay_seconds: float,
) -> None:
    """Download all posts from the specified user"""
    config = init_config()

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
        destination_directory = Path('./boosty-downloads').absolute()
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

            async with use_reporter(
                reporter=ProgressReporter(
                    logger=downloader_logger.logging_logger_obj,
                    console=downloader_logger.console,
                )
            ) as progress_reporter:
                download_all = DownloadAllPostUseCase(
                    author_name=username,
                    boosty_api=boosty_api_client,
                    destination=Path('./boosty-downloads') / username,
                    downloader_session=retry_client,
                    external_videos_downloader=ExternalVideosDownloader(),
                    filters=content_type_filter,
                    post_cache=SQLitePostCache(
                        destination=destination_directory / username,
                        logger=downloader_logger,
                    ),
                    progress_reporter=progress_reporter,
                )

                await download_all.execute()

            return  # I will get rid of this in the second refactor stage 🙏

            downloader = BoostyDownloadManager(
                general_options=GeneralOptions(
                    target_directory=destination_directory,
                    download_content_type_filters=content_type_filter,
                    request_delay_seconds=request_delay_seconds,
                    preferred_video_quality=preferred_video_quality,
                ),
                network_dependencies=NetworkDependencies(
                    session=retry_client,
                    api_client=boosty_api_client,
                    external_videos_downloader=ExternalVideosDownloader(),
                ),
                logger_dependencies=LoggerDependencies(
                    logger=downloader_logger,
                    failed_downloads_logger=FailedDownloadsLogger(
                        file_path=destination_directory
                        / username
                        / 'failed_downloads.txt',
                    ),
                ),
            )

            if check_total_count:
                await downloader.only_check_total_posts(username)
                return

            if post_url is not None:
                await downloader.download_post_by_url(username, post_url)
                return

            with SQLitePostCache(
                destination=destination_directory / username, logger=downloader.logger
            ) as sqlite_post_cache:
                if clean_cache:
                    sqlite_post_cache.remove_cache_completely()
                    return

                await downloader.download_all_posts(username, sqlite_post_cache)


@app.command()
def main_wrapper(  # noqa: PLR0913 (too many arguments because of typer)
    *,
    username: Annotated[
        str,
        typer.Option(),
    ],
    request_delay_seconds: Annotated[
        float,
        typer.Option(
            '--request-delay-seconds',
            '-d',
            help='Delay between requests to the API, in seconds',
            min=1,
        ),
    ] = 2.5,
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
    preferred_video_quality: Annotated[
        VideoQualityOption,
        typer.Option(
            '--preferred-video-quality',
            '-q',
            help='Preferred video quality option for downloader, will be considered during choosing video links, but if there is no suitable video quality - the best available will be used',
        ),
    ] = VideoQualityOption.medium,
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
    [bold]ABOUT:[/bold]

    ======
        CLI Tool to download posts from Boosty by author username.
        You can use the --post-url option to download only the specified post.
        Otherwise all posts will be downloaded from the newest to the oldest.

    [bold]CONTENT FILTERING:[/bold]

        You can specify several -f flags to choose what content to download.
        By default all flags are enabled.
        [italic]boosty-downloader --username <USERNAME> -f files -f post_content[/italic]

    [bold yellow]ABOUT RATE LIMITING:[/bold yellow]

        [bold]If you have error messages often[/bold], try to refresh auth/cookie with new one after re-login.
        Or increase [bold]request delay seconds[/bold] (default is 2.5).
        Also some wait can be helpful too, if you are restricted by the boosty.to itself.

        Anyways, remember, don't be rude and don't spam the API.
    """
    asyncio.run(
        main(
            username=username,
            check_total_count=check_total_count,
            clean_cache=clean_cache,
            post_url=post_url,
            content_type_filter=(
                content_type_filter
                if content_type_filter
                else list(DownloadContentTypeFilter)
            ),
            preferred_video_quality=preferred_video_quality,
            request_delay_seconds=request_delay_seconds,
        ),
    )


def bootstrap() -> None:
    """
    Run main entry point of the whole app.

    This run typer CLI using app() config.

    It doesn't run the app directly, but through main_wrapper,
    because main app by itself is async and can't be run directly with typer.
    """
    try:
        app()
    except BoostyAPINoUsernameError:
        logger_instances.downloader_logger.error('Username not found')
    except BoostyAPIUnauthorizedError:
        logger_instances.downloader_logger.error(
            'Unauthorized: Bad credentials, please relogin and update your config file'
        )
    except BoostyAPIUnknownError:
        logger_instances.downloader_logger.error(
            f'Unknown error occurred, please report this at GitHub issues of the project: {GITHUB_ISSUES_URL}'
        )
    except BoostyAPIValidationError as e:
        logger_instances.downloader_logger.error(
            'Boosty API returned unexpected structures, the client probably needs to be updated.\n'
            f'Please report this at GitHub issues of the project: {GITHUB_ISSUES_URL}\n'
            '\n'
            f'Details: {e.errors!s}'
        )
    except (OperationalError, DatabaseError, IntegrityError) as e:
        logger_instances.downloader_logger.error('⚠️  Cache Error!\n' + str(e))
        logger_instances.downloader_logger.warning(
            'Cache format may be outdated after application update.'
        )
        logger_instances.downloader_logger.info(
            '👉 You can clean outdated cache with --clean-cache flag'
        )
        logger_instances.downloader_logger.info(
            '👉 If this will still happen - please report it at GitHub issues:'
        )
        logger_instances.downloader_logger.info(f'👉 {GITHUB_ISSUES_URL}')


if __name__ == '__main__':
    bootstrap()
