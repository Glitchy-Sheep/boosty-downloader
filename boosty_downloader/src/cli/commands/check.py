"""CLI command: check total accessible/inaccessible posts count."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from boosty_downloader.src.application.di.initialized_app import initialized_app
from boosty_downloader.src.application.use_cases.check_total_posts import (
    ReportTotalPostsCountUseCase,
)
from boosty_downloader.src.cli.cli_options import (
    CacheDirectoryOption,  # noqa: TC001
    DestinationDirectoryOption,  # noqa: TC001
    RequestDelaySecondsOption,  # noqa: TC001
    UsernameOption,  # noqa: TC001
)
from boosty_downloader.src.infrastructure.loggers import logger_instances

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
        await ReportTotalPostsCountUseCase(
            author_name=username,
            logger=logger_instances.downloader_logger,
            boosty_api=app_env.boosty_api_client,
        ).execute()


def register(app: typer.Typer) -> None:
    """Register the check command."""

    @app.command(
        'check',
        short_help='See how many posts of some creator are accessible to you and which are not.',
    )
    def check_entrypoint(
        *,
        username: UsernameOption,
        request_delay_seconds: RequestDelaySecondsOption = 2.5,
        destination_directory: DestinationDirectoryOption = None,
        cache_directory: CacheDirectoryOption = None,
    ) -> None:
        """Check total count of accessible/inaccessible posts and exit without downloading."""
        asyncio.run(
            _check_handler(
                username=username,
                request_delay_seconds=request_delay_seconds,
                destination_directory=destination_directory,
                cache_directory=cache_directory,
            ),
        )
