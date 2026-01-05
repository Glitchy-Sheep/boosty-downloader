"""Main entrypoint of the app"""

from __future__ import annotations

import asyncio
import importlib.metadata
from typing import TYPE_CHECKING

import aiohttp
import typer
from aiohttp.client_exceptions import ClientConnectorDNSError
from aiohttp_retry import ExponentialRetry
from sqlalchemy.exc import DatabaseError, IntegrityError, OperationalError

from boosty_downloader.src.application.di.app_environment import AppEnvironment
from boosty_downloader.src.application.di.download_context import DownloadContext
from boosty_downloader.src.application.exceptions.application_errors import (
    ApplicationCancelledError,
)
from boosty_downloader.src.application.filtering import (
    DownloadContentTypeFilter,
    VideoQualityOption,
)
from boosty_downloader.src.application.use_cases.check_total_posts import (
    ReportTotalPostsCountUseCase,
)
from boosty_downloader.src.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.src.application.use_cases.download_specific_post import (
    DownloadPostByUrlUseCase,
)
from boosty_downloader.src.cli.cli_options import (
    # ---------------------------------------------------------------------------
    # These imports can't be moved to TYPE_CHECKING
    # because they are used by typer at runtime.
    #
    CheckTotalCountOption,  # noqa: TC001
    CleanCacheOption,  # noqa: TC001
    ContentTypeFilterOption,  # noqa: TC001
    DestinationDirectoryOption,  # noqa: TC001
    PostUrlOption,  # noqa: TC001
    PreferredVideoQualityOption,  # noqa: TC001
    RequestDelaySecondsOption,  # noqa: TC001
    UsernameOption,  # noqa: TC001
)
from boosty_downloader.src.infrastructure.boosty_api.core.client import (
    BoostyAPINoUsernameError,
    BoostyAPIUnauthorizedError,
    BoostyAPIUnknownError,
    BoostyAPIValidationError,
)
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
from boosty_downloader.src.infrastructure.update_checker.pypi_checker import (
    CheckFailed,
    NoUpdate,
    UpdateAvailable,
    check_for_updates,
)
from boosty_downloader.src.infrastructure.yaml_configuration.config import init_config

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.src.cli.console_progress_reporter import (
        ProgressReporter,
    )

typer_app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    rich_markup_mode='rich',
)

GITHUB_ISSUES_URL = 'https://github.com/Glitchy-Sheep/boosty-downloader/issues'


def show_start_summary(
    pr: ProgressReporter,
    destination_directory: Path,
    content_type_filter: list[DownloadContentTypeFilter],
) -> None:
    """Just simple review before start downloading"""
    pr.info(
        f'[italic]Destination directory[/italic]: [bold green]{destination_directory}[/bold green]'
    )
    pr.info(
        '----------------------------------------------------------------------------------\n'
        'Script will download: [bold green]'
        + ', '.join(str(item.name) for item in content_type_filter)
        + '[/bold green]\n'
        '----------------------------------------------------------------------------------\n'
    )
    pr.notice(
        'You can safely interrupt the download at any time with [bold yellow]Ctrl+C[/bold yellow].\n'
    )
    if DownloadContentTypeFilter.external_videos in content_type_filter:
        pr.notice(
            'Progress bar for external videos downloadings can be glitchy, because yt-dlp downloads them by chunks.\n'
            "If you see strange progress movement that's normal in most cases, just be patient.\n"
        )


async def typer_cmd_handler(  # noqa: PLR0913 (too many arguments because of typer)
    *,
    username: str,
    post_url: PostUrlOption | None,
    check_total_count: bool,
    clean_cache: bool,
    content_type_filter: list[DownloadContentTypeFilter],
    preferred_video_quality: VideoQualityOption,
    request_delay_seconds: float,
    destination_directory: Path | None,
) -> None:
    """Download all posts from the specified user"""
    config = init_config()

    cookie_string = config.auth.cookie
    auth_header = config.auth.auth_header

    # Set the destination directory if provided
    if destination_directory is not None:
        config.downloading_settings.target_directory = destination_directory

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

    # --------------------------------------------------------------------------
    # Check for updates and notify the user
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

    # --------------------------------------------------------------------------
    # Prepare app environment and start the task
    async with AppEnvironment(
        config=AppEnvironment.AppConfig(
            author_name=username,
            target_directory=config.downloading_settings.target_directory.absolute(),
            boosty_headers=parse_auth_header(auth_header),
            boosty_cookies_jar=parse_session_cookie(cookie_string),
            retry_options=retry_options,
            request_delay_seconds=request_delay_seconds,
            logger=logger_instances.downloader_logger,
        )
    ) as app_environment:
        downloading_context = DownloadContext(
            author_name=username,
            downloader_session=app_environment.downloading_retry_client,
            external_videos_downloader=ExternalVideosDownloader(),
            filters=content_type_filter,
            post_cache=app_environment.post_cache,
            preferred_video_quality=preferred_video_quality.to_ok_video_type(),
            progress_reporter=app_environment.progress_reporter,
            failed_logger=FailedDownloadsLogger(
                log_file_path=config.downloading_settings.target_directory
                / username
                / 'failed_downloads.log',
            ),
        )

        # ------------------------------------------------------------------
        # Cache cleaning
        if clean_cache:
            app_environment.post_cache.remove_cache_completely()
            logger_instances.downloader_logger.success(
                f'Cache for {username} has been cleaned successfully'
            )
            return

        # ------------------------------------------------------------------
        # Total Checker
        if check_total_count:
            await ReportTotalPostsCountUseCase(
                author_name=username,
                logger=logger_instances.downloader_logger,
                boosty_api=app_environment.boosty_api_client,
            ).execute()
            return

        # ------------------------------------------------------------------
        # Download specific post by URL
        if post_url is not None:
            await DownloadPostByUrlUseCase(
                post_url=post_url,
                boosty_api=app_environment.boosty_api_client,
                destination=app_environment.destination_directory,
                download_context=downloading_context,
            ).execute()
            return

        # ------------------------------------------------------------------
        # Download all posts

        show_start_summary(
            pr=app_environment.progress_reporter,
            destination_directory=app_environment.destination_directory,
            content_type_filter=content_type_filter,
        )

        await DownloadAllPostUseCase(
            author_name=username,
            boosty_api=app_environment.boosty_api_client,
            destination=app_environment.destination_directory,
            download_context=downloading_context,
        ).execute()


# Use wrapper because typer can't run async functions directly
@typer_app.command()
def typer_cmd_entrypoint(  # noqa: PLR0913 (too many arguments because of typer)
    *,
    username: UsernameOption,
    request_delay_seconds: RequestDelaySecondsOption = 2.5,
    post_url: PostUrlOption = None,
    content_type_filter: ContentTypeFilterOption = None,
    preferred_video_quality: PreferredVideoQualityOption = VideoQualityOption.medium,
    check_total_count: CheckTotalCountOption = False,
    clean_cache: CleanCacheOption = False,
    destination_directory: DestinationDirectoryOption = None,
) -> None:
    """
    [bold]ABOUT:[/bold]

    ======
        CLI tool to download Boosty posts by author username.

        - Use `--post-url` to download a specific post.
        - By default, downloads all posts from newest to oldest with all available contents.
        - Unavailable posts are skipped, and you will be notified about them.


    [bold]CONTENT FILTERING:[/bold]

        - Use multiple `-f` flags to select content types (all included by default).
        - Example: [italic]boosty-downloader --username <USERNAME> -f files -f post_content[/italic]
        - [bold red]NOTE:[/bold red] If you specify [italic]post_content[/italic] without [italic]boosty_videos[/italic] or [italic]external_videos[/italic],
                videos won't attach to post previews due to cache limitations.
        - For best results, just leave all filters by default.


    [bold]RATE LIMITING:[/bold]

        - Increase request delay (default 2.5s) if you get errors.
        - Please avoid spamming the API.


    [bold]ABOUT CONTENT SYNC & CACHING:[/bold]

        - Downloaded content is cached automatically to avoid duplicates.
        - Downloading the same post with different filters downloads only missing parts.
        - Posts updated by creators are fully re-downloaded.
        - Cache doesn't check local files, you can delete them and they still won't re-download.

    """
    asyncio.run(
        typer_cmd_handler(
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
            destination_directory=destination_directory,
        ),
    )


def entry_point() -> None:
    """
    Run main entry point of the whole app.

    This run typer CLI using app() config.

    It doesn't run the app directly, but through main_wrapper,
    because main app by itself is async and can't be run directly with typer.
    """
    try:
        typer_app()
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
    except ApplicationCancelledError:
        logger_instances.downloader_logger.warning(
            'Download cancelled by user, see you later! 💘\n'
        )
    except ClientConnectorDNSError:
        logger_instances.downloader_logger.error(
            'Network error: Unable to connect to Boosty API, please check your internet connection.'
        )
    except (
        OperationalError,
        DatabaseError,
        IntegrityError,
    ) as e:
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
    entry_point()
