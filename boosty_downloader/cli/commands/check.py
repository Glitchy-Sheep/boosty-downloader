"""CLI command: show the blog overview without downloading."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from boosty_downloader.application.di.initialized_app import initialized_app
from boosty_downloader.application.use_cases.check_total_posts import (
    ReportTotalPostsCountUseCase,
)
from boosty_downloader.cli.blog_overview_rendering import render_blog_overview
from boosty_downloader.cli.cli_options import (
    CacheDirectoryOption,  # noqa: TC001
    DestinationDirectoryOption,  # noqa: TC001
    RequestDelaySecondsOption,  # noqa: TC001
    UsernameOption,  # noqa: TC001
)
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
) -> None:
    async with initialized_app(
        username=username,
        request_delay_seconds=request_delay_seconds,
        destination_directory=destination_directory,
        cache_directory=cache_directory,
    ) as app_env:
        report = await ReportTotalPostsCountUseCase(
            author_name=username,
            logger=logger_instances.downloader_logger,
            boosty_api=app_env.boosty_api_client,
        ).execute()
        logger_instances.downloader_logger.success(
            # Local time: "last post N days ago" must follow the user's calendar.
            render_blog_overview(
                report.overview, now=datetime.now(timezone.utc).astimezone()
            )
        )
        if report.problems:
            logger_instances.downloader_logger.warning(report.problems)


def register(app: typer.Typer) -> None:
    """Register the check command."""

    @app.command(
        'check',
        short_help='Show the blog overview: posts by tier with prices, media counts, dates.',
    )
    def check_entrypoint(
        *,
        username: UsernameOption,
        request_delay_seconds: RequestDelaySecondsOption = 2.5,
        destination_directory: DestinationDirectoryOption = None,
        cache_directory: CacheDirectoryOption = None,
    ) -> None:
        """Show how many posts you can access, what unlocks the rest and what media they carry - without downloading."""
        asyncio.run(
            _check_handler(
                username=username,
                request_delay_seconds=request_delay_seconds,
                destination_directory=destination_directory,
                cache_directory=cache_directory,
            ),
        )
