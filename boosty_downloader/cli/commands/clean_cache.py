"""CLI command: clean download cache for a user."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

from typing import TYPE_CHECKING

import typer

from boosty_downloader.application.use_cases.clean_cache import (
    CleanCacheOutcome,
    CleanCacheUseCase,
)
from boosty_downloader.cli.cli_options import (
    CacheDirectoryOption,
    UsernameArgument,
    YesOption,
    global_options,
)
from boosty_downloader.cli.composition_root import resolve_cache_dir
from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.post_caching.storage import SQLiteCacheStorage

if TYPE_CHECKING:
    from pathlib import Path


def _clean_cache(
    *,
    username: str,
    config_path: Path,
    cache_directory: Path | None,
    yes: bool,
) -> None:
    cache_dir = resolve_cache_dir(
        username=username, config_path=config_path, cache_directory=cache_directory
    )

    def confirm() -> bool:
        return yes or typer.confirm(
            f'Cache for {username} will be removed, '
            'the next run downloads everything again. Continue?'
        )

    outcome = CleanCacheUseCase(
        SQLiteCacheStorage(cache_dir), confirm=confirm
    ).execute()

    logger = logger_instances.downloader_logger
    match outcome:
        case CleanCacheOutcome.nothing_to_clean:
            logger.info(f'No cache found for {username} - nothing to clean')
        case CleanCacheOutcome.cancelled:
            logger.info(f'Cache for {username} is kept')
        case CleanCacheOutcome.cleaned:
            logger.success(f'Cache for {username} has been cleaned successfully')


def register(app: typer.Typer) -> None:
    """Register the clean-cache command."""

    @app.command(
        'clean-cache',
        short_help='Remove cached post data for a creator.',
    )
    def clean_cache_entrypoint(
        ctx: typer.Context,
        *,
        username: UsernameArgument,
        cache_directory: CacheDirectoryOption = None,
        yes: YesOption = False,
    ) -> None:
        """
        Remove the posts cache for the selected username completely.

        The cache is the only record of what was downloaded: after it is
        removed, the next download run fetches every post again. The command
        asks before removing; pass --yes to skip the question in scripts.
        """
        _clean_cache(
            username=username,
            config_path=global_options(ctx).config_path,
            cache_directory=cache_directory,
            yes=yes,
        )
