"""CLI command: clean download cache for a user."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.src.cli.cli_options import (
    CacheDirectoryOption,  # noqa: TC001
    UsernameOption,  # noqa: TC001
)
from boosty_downloader.src.infrastructure.loggers import logger_instances
from boosty_downloader.src.infrastructure.post_caching.post_cache import SQLitePostCache
from boosty_downloader.src.infrastructure.yaml_configuration.config import init_config

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

    with SQLitePostCache(
        destination=cache_dir.absolute() / username,
        logger=logger_instances.downloader_logger,
    ) as post_cache:
        post_cache.remove_cache_completely()

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
