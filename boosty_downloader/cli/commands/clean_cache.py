"""CLI command: clean download cache for a user."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.use_cases.clean_cache import (
    CleanCacheOutcome,
    CleanCacheUseCase,
)
from boosty_downloader.cli.cli_options import (
    CacheDirectoryOption,  # noqa: TC001
    UsernameArgument,  # noqa: TC001
)
from boosty_downloader.cli.composition_root import load_settings
from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.post_caching.storage import SQLiteCacheStorage

if TYPE_CHECKING:
    from pathlib import Path

    import typer


def _clean_cache(
    *,
    username: str,
    cache_directory: Path | None,
) -> None:
    settings = load_settings(username=username, cache_directory=cache_directory)
    outcome = CleanCacheUseCase(SQLiteCacheStorage(settings.cache_dir)).execute()

    logger = logger_instances.downloader_logger
    match outcome:
        case CleanCacheOutcome.nothing_to_clean:
            logger.info(f'No cache found for {username} - nothing to clean')
        case CleanCacheOutcome.cleaned:
            logger.success(f'Cache for {username} has been cleaned successfully')


def register(app: typer.Typer) -> None:
    """Register the clean-cache command."""

    @app.command(
        'clean-cache',
        short_help='Remove cached post data for a creator.',
    )
    def clean_cache_entrypoint(
        *,
        username: UsernameArgument,
        cache_directory: CacheDirectoryOption = None,
    ) -> None:
        """Remove the posts cache for the selected username completely."""
        _clean_cache(
            username=username,
            cache_directory=cache_directory,
        )
