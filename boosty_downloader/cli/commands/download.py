"""CLI command: download posts from a Boosty creator."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import typer

from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.filtering import (
    VideoQualityOption,
)
from boosty_downloader.application.post_preparation import PostPreparer
from boosty_downloader.application.post_retry import PostOutcome
from boosty_downloader.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.application.use_cases.download_post_by_id import (
    DownloadPostByIdUseCase,
)
from boosty_downloader.application.use_cases.plan_download import (
    PlanDownloadUseCase,
)
from boosty_downloader.cli.cli_options import (
    CacheDirectoryOption,
    ContentTypeFilterOption,
    DestinationDirectoryOption,
    DryRunOption,
    ExcludeTagOption,
    PostUrlOption,
    PreferredVideoQualityOption,
    RequestDelaySecondsOption,
    RestoreMissingOption,
    SkipAllFailuresOption,
    UsernameArgument,
    global_options,
)
from boosty_downloader.cli.composition_root import load_settings, open_app
from boosty_downloader.cli.error_reporting import report_command_errors
from boosty_downloader.cli.update_check import notify_about_updates
from boosty_downloader.cli.views.blog_overview import render_blog_overview
from boosty_downloader.cli.views.download_plan import render_download_plan
from boosty_downloader.cli.views.run_statistics import render_run_statistics
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.infrastructure.boosty_api.utils.post_url import (
    InvalidPostUrlError,
    parse_post_url,
)
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.loggers.debug_file import debug_logging
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


async def _dry_run_handler(  # noqa: PLR0913 - independent download options
    app: App,
    *,
    settings: AppSettings,
    content_type_filter: list[DownloadContentTypeFilter],
    preferred_video_quality: VideoQualityOption,
    excluded_tags: tuple[str, ...] = (),
    restore_missing: bool = False,
) -> None:
    """Print the overview and the plan of a would-be run; download nothing."""
    report = await PlanDownloadUseCase(
        author_name=settings.author_name,
        boosty_api=app.api,
        logger=logger_instances.downloader_logger,
        preparer=PostPreparer(
            library_root=settings.library_root,
            store=app.post_store,
            author=settings.author_name,
            preferred_video_quality=preferred_video_quality.to_ok_video_type(),
            restore_missing=restore_missing,
        ),
        filters=content_type_filter,
        excluded_tags=excluded_tags,
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


def _post_id_of(post_url: str, username: str) -> str:
    """Read the post id off the url; the post must belong to USERNAME."""
    try:
        post = parse_post_url(post_url)
    except InvalidPostUrlError as e:
        raise typer.BadParameter(str(e), param_hint='--post-url') from e
    if post.author_name != username:
        msg = (
            f'the post belongs to {post.author_name!r}, not to {username!r}: '
            f'run the command with {post.author_name!r} as USERNAME'
        )
        raise typer.BadParameter(msg, param_hint='--post-url')
    return post.post_id


async def _download_handler(  # noqa: PLR0913
    *,
    username: str,
    config_path: Path,
    post_id: str | None,
    content_type_filter: list[DownloadContentTypeFilter],
    preferred_video_quality: VideoQualityOption,
    request_delay_seconds: float,
    destination_directory: Path | None,
    cache_directory: Path | None,
    skip_all_failures: bool,
    dry_run: bool,
    excluded_tags: tuple[str, ...] = (),
    restore_missing: bool = False,
) -> None:
    logger = logger_instances.downloader_logger
    settings = load_settings(
        username=username,
        config_path=config_path,
        destination_directory=destination_directory,
        cache_directory=cache_directory,
        read_only=dry_run,
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
                excluded_tags=excluded_tags,
                restore_missing=restore_missing,
            )
            return

        downloading_context = DownloadContext(
            author_name=settings.author_name,
            downloader_session=app.media_http,
            external_videos_downloader=ExternalVideosDownloader(),
            filters=content_type_filter,
            excluded_tags=excluded_tags,
            restore_missing=restore_missing,
            post_store=app.post_store,
            library_root=settings.library_root,
            preferred_video_quality=preferred_video_quality.to_ok_video_type(),
            progress_reporter=app.reporter,
            failed_logger=FailedDownloadsLogger(
                log_file_path=settings.destination_dir / 'failed_downloads.log',
            ),
        )

        failed = False
        try:
            if post_id is not None:
                outcome = await DownloadPostByIdUseCase(
                    post_id=post_id,
                    boosty_api=app.api,
                    destination=settings.destination_dir,
                    download_context=downloading_context,
                ).execute()
                failed = outcome is not PostOutcome.downloaded
            else:
                _show_start_summary(
                    pr=app.reporter,
                    destination_directory=settings.destination_dir,
                    content_type_filter=content_type_filter,
                )
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
        if failed:
            # Scripts rely on the exit code: a failed download is not a success.
            raise typer.Exit(1)


def register(app: typer.Typer) -> None:
    """Register the download command."""

    @app.command(
        'download',
        short_help='Download posts from a Boosty creator.',
    )
    def download_entrypoint(  # noqa: PLR0913
        ctx: typer.Context,
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
        restore_missing: RestoreMissingOption = False,
        exclude_tag: ExcludeTagOption = None,
    ) -> None:
        """
        Download posts from a Boosty creator: boosty-downloader download USERNAME

        [bold]DETAILS:[/bold]

            - Use `--post-url` to download a specific post.
            - Use `--dry-run` to preview a run: new and updated posts, media to fetch and the known size - no files are created or changed.
            - By default, downloads all posts from newest to oldest with all available contents.
            - Unavailable posts are skipped, and you will be notified about them.
            - Every run ends with statistics: posts, media by type, total size and time.


        [bold]CONTENT FILTERING:[/bold]

            - Use multiple `-f` flags to select content types (all included by default).
            - Example: [italic]boosty-downloader download <USERNAME> -f files -f post_content[/italic]
            - Every saved page describes the complete post, including media not selected for download.
            - Filters choose which media to fetch; later runs can add other media to the same page.
            - Use `--exclude-tag TAG` to skip posts with a tag (whole name, case-insensitive); repeat for multiple tags.


        [bold]RATE LIMITING:[/bold]

            - Increase request delay (default 2.5s) if you get errors.
            - Please avoid spamming the API.


        [bold]ABOUT SAVED POSTS:[/bold]

            - Saved post records in the destination library track content and downloaded media.
            - A later run reuses saved media, adds newly selected media and retries failed downloads.
            - Updated text and metadata refresh the page without downloading unchanged media.
            - Files you remove locally stay removed unless you use --restore-missing.
            - --restore-missing restores selected missing media still present in the post; combine it with --dry-run to preview.
            - The legacy --cache-dir option does not control these records.

        """
        excluded_tags = tuple(tag.strip() for tag in exclude_tag or ())
        if any(not tag for tag in excluded_tags):
            msg = 'tag must not be empty'
            raise typer.BadParameter(msg, param_hint='--exclude-tag')
        if dry_run and post_url is not None:
            msg = '--dry-run previews the full-blog run; combine it with --post-url is not supported'
            raise typer.BadParameter(msg)
        # A broken link or a post of another creator fails here, before any
        # config is read or request is made.
        post_id = _post_id_of(post_url, username) if post_url is not None else None
        options = global_options(ctx)
        with (
            debug_logging(enabled=options.debug, read_only=dry_run),
            report_command_errors(read_only=dry_run),
        ):
            asyncio.run(
                _download_handler(
                    username=username,
                    config_path=options.config_path,
                    post_id=post_id,
                    content_type_filter=(
                        content_type_filter or list(DownloadContentTypeFilter)
                    ),
                    preferred_video_quality=preferred_video_quality,
                    excluded_tags=excluded_tags,
                    request_delay_seconds=request_delay_seconds,
                    destination_directory=destination_directory,
                    cache_directory=cache_directory,
                    skip_all_failures=skip_all_failures,
                    dry_run=dry_run,
                    restore_missing=restore_missing,
                ),
            )
