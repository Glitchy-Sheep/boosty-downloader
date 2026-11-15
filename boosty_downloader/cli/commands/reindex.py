"""CLI command: rebuild the disposable index from canonical library records."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

from typing import TYPE_CHECKING

import typer
from sqlalchemy.exc import SQLAlchemyError

from boosty_downloader.cli.cli_options import (
    CacheDirectoryOption,
    DestinationDirectoryOption,
    global_options,
)
from boosty_downloader.cli.composition_root import (
    resolve_index_path,
    resolve_library_root,
)
from boosty_downloader.cli.error_reporting import (
    point_at_the_debug_log,
    report_command_errors,
)
from boosty_downloader.cli.views.library_maintenance import (
    render_reindex_failure,
    render_reindex_result,
)
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.library_format import (
    check_library_compatibility,
)
from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.loggers.debug_file import debug_logging

if TYPE_CHECKING:
    from pathlib import Path


def _rebuild_index(root: Path, index_path: Path | None) -> None:
    index = LibraryIndex(root, index_path=index_path)
    try:
        counts = index.rebuild()
        path = index.path
    except (OSError, ValueError, RuntimeError, SQLAlchemyError) as error:
        logger_instances.downloader_logger.error(
            render_reindex_failure(path=index.configured_path, reason=str(error))
        )
        point_at_the_debug_log()
        raise typer.Exit(1) from error
    logger_instances.downloader_logger.success(
        render_reindex_result(authors=counts.authors, posts=counts.posts, path=path)
    )


def register(app: typer.Typer) -> None:
    """Register the offline, whole-library reindex command."""

    @app.command('reindex', short_help='Rebuild the library search index offline.')
    def reindex_entrypoint(
        ctx: typer.Context,
        *,
        destination_directory: DestinationDirectoryOption = None,
        cache_directory: CacheDirectoryOption = None,
    ) -> None:
        """
        Rebuild the whole library index from saved records without network access.

        Credentials are not required. Saved records, viewing marks, pages and media are kept unchanged. Use -o to select the library and --cache-dir to place index.db on a writable local disk. Otherwise the folders from config.yaml apply, with the index inside the library by default.
        """
        options = global_options(ctx)
        with report_command_errors(read_only=True):
            root = resolve_library_root(
                config_path=options.config_path,
                destination_directory=destination_directory,
            )
            check_library_compatibility(root)
            index_path = resolve_index_path(
                config_path=options.config_path, cache_directory=cache_directory
            )
        with debug_logging(enabled=options.debug):
            _rebuild_index(root, index_path)
