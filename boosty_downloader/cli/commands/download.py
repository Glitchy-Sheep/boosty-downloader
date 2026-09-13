"""CLI command: download posts from a Boosty creator."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import typer

from boosty_downloader.application.download_context import DownloadContext
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
from boosty_downloader.application.use_cases.plan_download import (
    PlanDownloadUseCase,
)
from boosty_downloader.cli.cli_options import (
    CacheDirectoryOption,  # noqa: TC001
    ContentTypeFilterOption,  # noqa: TC001
    DestinationDirectoryOption,  # noqa: TC001
    DryRunOption,  # noqa: TC001
    PostUrlOption,  # noqa: TC001
    PreferredVideoQualityOption,  # noqa: TC001
    RequestDelaySecondsOption,  # noqa: TC001
    SkipAllFailuresOption,  # noqa: TC001
    UsernameArgument,  # noqa: TC001
)
from boosty_downloader.cli.composition_root import load_settings, open_app
from boosty_downloader.cli.update_check import notify_about_updates
from boosty_downloader.cli.views.blog_overview import render_blog_overview
from boosty_downloader.cli.views.download_plan import render_download_plan
from boosty_downloader.cli.views.run_statistics import render_run_statistics
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.loggers.failed_downloads_logger import (
    FailedDownloadsLogger,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import ProgressReporter
    from boosty_downloader.cli.composition_root import App, AppSettings


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


async def _dry_run_handler(
    app: App,
    *,
    settings: AppSettings,
    content_type_filter: list[DownloadContentTypeFilter],
    preferred_video_quality: VideoQualityOption,
) -> None:
    """Print the overview and the plan of a would-be run; download nothing."""
    report = await PlanDownloadUseCase(
        author_name=settings.author_name,
        boosty_api=app.api,
        logger=logger_instances.downloader_logger,
        post_cache=app.cache,
        filters=content_type_filter,
        preferred_video_quality=preferred_video_quality.to_ok_video_type(),
    ).execute()
    console = app.reporter.console
    console.print(
        render_blog_overview(
            report.overview, now=datetime.now(timezone.utc).astimezone()
        )
    )
    console.print(render_download_plan(report.plan, filters=content_type_filter))
    if report.problems:
        logger_instances.downloader_logger.warning(report.problems)


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
    dry_run: bool,
) -> None:
    logger = logger_instances.downloader_logger
    settings = load_settings(
        username=username,
        destination_directory=destination_directory,
        cache_directory=cache_directory,
    )
    await notify_about_updates(logger)

    async with open_app(
        settings, request_delay_seconds=request_delay_seconds, logger=logger
    ) as app:
        if dry_run:
            await _dry_run_handler(
                app,
                settings=settings,
                content_type_filter=content_type_filter,
                preferred_video_quality=preferred_video_quality,
            )
            return

        downloading_context = DownloadContext(
            author_name=settings.author_name,
            downloader_session=app.media_http,
            external_videos_downloader=ExternalVideosDownloader(),
            filters=content_type_filter,
            post_cache=app.cache,
            preferred_video_quality=preferred_video_quality.to_ok_video_type(),
            progress_reporter=app.reporter,
            failed_logger=FailedDownloadsLogger(
                log_file_path=settings.destination_dir / 'failed_downloads.log',
            ),
        )

        if post_url is not None:
            outcome = await DownloadPostByUrlUseCase(
                post_url=post_url,
                boosty_api=app.api,
                destination=settings.destination_dir,
                download_context=downloading_context,
            ).execute()
            if outcome is PostOutcome.failed:
                # Scripts rely on the exit code: a failed download is not a success.
                raise typer.Exit(1)
            return

        _show_start_summary(
            pr=app.reporter,
            destination_directory=settings.destination_dir,
            content_type_filter=content_type_filter,
        )

        try:
            await DownloadAllPostUseCase(
                author_name=settings.author_name,
                boosty_api=app.api,
                destination=settings.destination_dir,
                download_context=downloading_context,
                skip_all_failures=skip_all_failures,
            ).execute()
        finally:
            # Also after a systemic stop or Ctrl+C: what got done is still news.
            stats = downloading_context.run_statistics
            app.reporter.console.print(
                render_run_statistics(stats, elapsed_seconds=stats.elapsed_seconds())
            )


def register(app: typer.Typer) -> None:
    """Register the download command."""

    @app.command(
        'download',
        short_help='Download posts from a Boosty creator.',
    )
    def download_entrypoint(  # noqa: PLR0913
        *,
        username: UsernameArgument,
        request_delay_seconds: RequestDelaySecondsOption = 2.5,
        post_url: PostUrlOption = None,
        content_type_filter: ContentTypeFilterOption = None,
        preferred_video_quality: PreferredVideoQualityOption = VideoQualityOption.medium,
        destination_directory: DestinationDirectoryOption = None,
        cache_directory: CacheDirectoryOption = None,
        skip_all_failures: SkipAllFailuresOption = False,
        dry_run: DryRunOption = False,
    ) -> None:
        """
        Download posts from a Boosty creator: boosty-downloader download USERNAME

        [bold]DETAILS:[/bold]

            - Use `--post-url` to download a specific post.
            - Use `--dry-run` to preview a run: new and updated posts, media to fetch and the known size - nothing is downloaded.
            - By default, downloads all posts from newest to oldest with all available contents.
            - Unavailable posts are skipped, and you will be notified about them.
            - Every run ends with statistics: posts, media by type, total size and time.


        [bold]CONTENT FILTERING:[/bold]

            - Use multiple `-f` flags to select content types (all included by default).
            - Example: [italic]boosty-downloader download <USERNAME> -f files -f post_content[/italic]
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
        if dry_run and post_url is not None:
            msg = '--dry-run previews the full-blog run; combine it with --post-url is not supported'
            raise typer.BadParameter(msg)
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
                dry_run=dry_run,
            ),
        )
