"""CLI command: clean download cache for a user."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from boosty_downloader.cli.cli_options import (
    CacheDirectoryOption,  # noqa: TC001
    UsernameOption,  # noqa: TC001
)
from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.post_caching.post_cache import SQLitePostCache
from boosty_downloader.infrastructure.yaml_configuration.config import init_config

if TYPE_CHECKING:
    from pathlib import Path

    import typer


def _clean_cache(
    *,
    username: str,
    cache_directory: Path | None,
) -> None:
    config = init_config()

    if cache_directory is not None:
        config.downloading_settings.cache_directory = cache_directory

    cache_dir = (
        config.downloading_settings.cache_directory
        or config.downloading_settings.target_directory
    )

    # Opening SQLitePostCache creates the database, so a missing cache
    # must be answered before that - otherwise the command fabricates
    # an empty cache and reports a false success.
    cache_db = cache_dir.absolute() / username / SQLitePostCache.DEFAULT_CACHE_FILENAME
    if not cache_db.exists():
        logger_instances.downloader_logger.info(
            f'No cache found for {username} - nothing to clean'
        )
        return

    with SQLitePostCache(
        destination=cache_dir.absolute() / username,
        logger=logger_instances.downloader_logger,
    ) as post_cache:
        post_cache.remove_cache_completely()

    # remove_cache_completely recreates an empty database right away;
    # drop it so a repeated clean honestly says there is nothing to clean.
    cache_db.unlink(missing_ok=True)
    with suppress(OSError):
        # Keep the folder when it still holds downloaded posts.
        cache_db.parent.rmdir()

    logger_instances.downloader_logger.success(
        f'Cache for {username} has been cleaned successfully'
    )


def register(app: typer.Typer) -> None:
    """Register the clean-cache command."""

    @app.command(
        'clean-cache',
        short_help='Remove cached post data for a creator.',
    )
    def clean_cache_entrypoint(
        *,
        username: UsernameOption,
        cache_directory: CacheDirectoryOption = None,
    ) -> None:
        """Remove the posts cache for the selected username completely."""
        _clean_cache(
            username=username,
            cache_directory=cache_directory,
        )
