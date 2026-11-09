"""CLI command: browse a local library without Boosty credentials."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer
from rich.markup import escape
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
from boosty_downloader.cli.error_reporting import report_command_errors
from boosty_downloader.cli.views.viewer import (
    empty_library_message,
    render_viewer_failure,
    render_viewer_started,
)
from boosty_downloader.infrastructure.library.library_format import (
    LibraryCompatibilityError,
    check_library_compatibility,
)
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader
from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.loggers.debug_file import debug_logging
from boosty_downloader.viewer.app import LibraryNotice, create_app
from boosty_downloader.viewer.server import (
    MAX_PORT,
    ServerOptions,
    serve,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.viewer.server import ServerAddresses

PortOption = Annotated[
    int | None,
    typer.Option(
        '--port',
        min=1,
        max=MAX_PORT,
        help='Listen on this port; fail if busy. By default try 8314, then the next free port.',
        show_default=False,
    ),
]
LanOption = Annotated[
    bool,
    typer.Option(
        '--lan', help='Allow devices on your local network to browse the library.'
    ),
]
NoOpenOption = Annotated[
    bool,
    typer.Option(
        '--no-open', help='Print the viewer address without opening a browser.'
    ),
]


def _announce(addresses: ServerAddresses) -> None:
    logger_instances.downloader_logger.info(render_viewer_started(addresses))


def _blocked_library(root: Path) -> LibraryNotice | None:
    try:
        check_library_compatibility(root)
    except LibraryCompatibilityError as error:
        return LibraryNotice(title='Library unavailable', message=str(error))
    return None


def _serve_library(root: Path, index_path: Path | None, server: ServerOptions) -> None:
    reader = JsonLibraryReader(root, index_path=index_path)
    reader.prepare()
    notice = None
    if not reader.authors():
        message = empty_library_message(root)
        logger_instances.downloader_logger.info(escape(message))
        notice = LibraryNotice(title='No library yet', message=message)
    serve(
        create_app(reader=reader, notice=notice), options=server, on_started=_announce
    )


def _view(
    *,
    root: Path,
    config_path: Path,
    cache_directory: Path | None,
    server: ServerOptions,
    debug: bool,
) -> None:
    if notice := _blocked_library(root):
        logger_instances.downloader_logger.error(escape(notice.message))
        serve(
            create_app(reader=None, notice=notice), options=server, on_started=_announce
        )
        return
    index_path = resolve_index_path(
        config_path=config_path, cache_directory=cache_directory
    )
    with debug_logging(enabled=debug):
        _serve_library(root, index_path, server)


def register(app: typer.Typer) -> None:
    """Register local browsing with path-only configuration and safe preflight."""

    @app.command('view', short_help='Browse the local library in your browser.')
    def view_entrypoint(  # noqa: PLR0913
        ctx: typer.Context,
        *,
        destination_directory: DestinationDirectoryOption = None,
        cache_directory: CacheDirectoryOption = None,
        port: PortOption = None,
        lan: LanOption = False,
        no_open: NoOpenOption = False,
    ) -> None:
        """Browse saved posts without credentials. Use --lan to share with local devices."""
        options = global_options(ctx)
        with report_command_errors(read_only=True):
            root = resolve_library_root(
                config_path=options.config_path,
                destination_directory=destination_directory,
            )
        try:
            _view(
                root=root,
                config_path=options.config_path,
                cache_directory=cache_directory,
                server=ServerOptions(port=port, lan=lan, open_browser=not no_open),
                debug=options.debug,
            )
        except (OSError, ValueError, RuntimeError, SQLAlchemyError) as error:
            logger_instances.downloader_logger.error(render_viewer_failure(str(error)))
            raise typer.Exit(1) from error
