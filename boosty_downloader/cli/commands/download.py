"""CLI command: download posts from a Boosty creator."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import typer

from boosty_downloader.application.di.download_context import DownloadContext
from boosty_downloader.application.di.initialized_app import initialized_app
from boosty_downloader.application.filtering import (
    DownloadContentTypeFilter,
    VideoQualityOption,
)
from boosty_downloader.application.post_retry import PostOutcome
from boosty_downloader.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.application.use_cases.download_specific_post import (
    DownloadPostByUrlUseCase,
)
from boosty_downloader.cli.cli_options import (
    CacheDirectoryOption,  # noqa: TC001
    ContentTypeFilterOption,  # noqa: TC001
    DestinationDirectoryOption,  # noqa: TC001
    PostUrlOption,  # noqa: TC001
    PreferredVideoQualityOption,  # noqa: TC001
    RequestDelaySecondsOption,  # noqa: TC001
    SkipAllFailuresOption,  # noqa: TC001
    UsernameOption,  # noqa: TC001
)
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.infrastructure.loggers.failed_downloads_logger import (
    FailedDownloadsLogger,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.cli.console_progress_reporter import (
        ProgressReporter,
    )


def _show_start_summary(
    pr: ProgressReporter,
    destination_directory: Path,
    content_type_filter: list[DownloadContentTypeFilter],
) -> None:
    """Display a summary before starting the download."""
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


async def _download_handler(  # noqa: PLR0913
    *,
    username: str,
    post_url: str | None,
    content_type_filter: list[DownloadContentTypeFilter],
    preferred_video_quality: VideoQualityOption,
    request_delay_seconds: float,
    destination_directory: Path | None,
    cache_directory: Path | None,
    skip_all_failures: bool,
) -> None:
    async with initialized_app(
        username=username,
        request_delay_seconds=request_delay_seconds,
        destination_directory=destination_directory,
        cache_directory=cache_directory,
    ) as app_env:
        downloading_context = DownloadContext(
            author_name=username,
            downloader_session=app_env.downloading_retry_client,
            external_videos_downloader=ExternalVideosDownloader(),
            filters=content_type_filter,
            post_cache=app_env.post_cache,
            preferred_video_quality=preferred_video_quality.to_ok_video_type(),
            progress_reporter=app_env.progress_reporter,
            failed_logger=FailedDownloadsLogger(
                log_file_path=app_env.destination_directory / 'failed_downloads.log',
            ),
        )

        if post_url is not None:
            outcome = await DownloadPostByUrlUseCase(
                post_url=post_url,
                boosty_api=app_env.boosty_api_client,
                destination=app_env.destination_directory,
                download_context=downloading_context,
            ).execute()
            if outcome is PostOutcome.failed:
                # Scripts rely on the exit code: a failed download is not a success.
                raise typer.Exit(1)
            return

        _show_start_summary(
            pr=app_env.progress_reporter,
            destination_directory=app_env.destination_directory,
            content_type_filter=content_type_filter,
        )

        await DownloadAllPostUseCase(
            author_name=username,
            boosty_api=app_env.boosty_api_client,
            destination=app_env.destination_directory,
            download_context=downloading_context,
            skip_all_failures=skip_all_failures,
        ).execute()


def register(app: typer.Typer) -> None:
    """Register the download command."""

    @app.command(
        'download',
        short_help='Download posts from a Boosty creator.',
    )
    def download_entrypoint(  # noqa: PLR0913
        *,
        username: UsernameOption,
        request_delay_seconds: RequestDelaySecondsOption = 2.5,
        post_url: PostUrlOption = None,
        content_type_filter: ContentTypeFilterOption = None,
        preferred_video_quality: PreferredVideoQualityOption = VideoQualityOption.medium,
        destination_directory: DestinationDirectoryOption = None,
        cache_directory: CacheDirectoryOption = None,
        skip_all_failures: SkipAllFailuresOption = False,
    ) -> None:
        """
        Download posts from a Boosty creator.

        [bold]DETAILS:[/bold]

            - Use `--post-url` to download a specific post.
            - By default, downloads all posts from newest to oldest with all available contents.
            - Unavailable posts are skipped, and you will be notified about them.


        [bold]CONTENT FILTERING:[/bold]

            - Use multiple `-f` flags to select content types (all included by default).
            - Example: [italic]boosty-downloader download --username <USERNAME> -f files -f post_content[/italic]
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
            _download_handler(
                username=username,
                post_url=post_url,
                content_type_filter=(
                    content_type_filter or list(DownloadContentTypeFilter)
                ),
                preferred_video_quality=preferred_video_quality,
                request_delay_seconds=request_delay_seconds,
                destination_directory=destination_directory,
                cache_directory=cache_directory,
                skip_all_failures=skip_all_failures,
            ),
        )
