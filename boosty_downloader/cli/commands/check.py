"""CLI command: show the blog overview without downloading."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from boosty_downloader.application.use_cases.check_total_posts import (
    ReportTotalPostsCountUseCase,
)
from boosty_downloader.cli.cli_options import (
    CacheDirectoryOption,  # noqa: TC001
    DestinationDirectoryOption,  # noqa: TC001
    RequestDelaySecondsOption,  # noqa: TC001
    ShowPostsOption,  # noqa: TC001
    UsernameArgument,  # noqa: TC001
)
from boosty_downloader.cli.composition_root import load_settings, open_app
from boosty_downloader.cli.update_check import notify_about_updates
from boosty_downloader.cli.views.blog_overview import render_blog_overview
from boosty_downloader.infrastructure.loggers import logger_instances

if TYPE_CHECKING:
    from pathlib import Path

    import typer


async def _check_handler(
    *,
    username: str,
    request_delay_seconds: float,
    destination_directory: Path | None,
    cache_directory: Path | None,
    show_posts: bool,
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
        report = await ReportTotalPostsCountUseCase(
            author_name=settings.author_name,
            logger=logger,
            boosty_api=app.api,
        ).execute()
        # Local time: "last post N days ago" must follow the user's calendar.
        app.reporter.console.print(
            render_blog_overview(
                report.overview,
                now=datetime.now(timezone.utc).astimezone(),
                show_posts=show_posts,
            )
        )
        if report.problems:
            logger.warning(report.problems)


def register(app: typer.Typer) -> None:
    """Register the check command."""

    @app.command(
        'check',
        short_help='Show what each subscription tier gives, where you stand and what the rest costs.',
    )
    def check_entrypoint(
        *,
        username: UsernameArgument,
        request_delay_seconds: RequestDelaySecondsOption = 2.5,
        destination_directory: DestinationDirectoryOption = None,
        cache_directory: CacheDirectoryOption = None,
        posts: ShowPostsOption = False,
    ) -> None:
        """Show what each subscription tier gives, where you stand and what the rest costs - without downloading."""
        asyncio.run(
            _check_handler(
                username=username,
                request_delay_seconds=request_delay_seconds,
                destination_directory=destination_directory,
                cache_directory=cache_directory,
                show_posts=posts,
            ),
        )
