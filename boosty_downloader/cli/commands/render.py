"""CLI command: rebuild saved post pages without contacting Boosty."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

import typer

from boosty_downloader.application.use_cases.render_posts import RenderPostsUseCase
from boosty_downloader.cli.cli_options import (
    DestinationDirectoryOption,
    global_options,
)
from boosty_downloader.cli.composition_root import resolve_library_root
from boosty_downloader.cli.error_reporting import (
    point_at_the_debug_log,
    report_command_errors,
)
from boosty_downloader.cli.views.render_result import (
    render_pages_failure,
    render_pages_result,
)
from boosty_downloader.infrastructure.library._record_paths import validate_author_name
from boosty_downloader.infrastructure.library.library_format import (
    check_library_compatibility,
)
from boosty_downloader.infrastructure.library.page_links import SavedPageLinkResolver
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords
from boosty_downloader.infrastructure.loggers import logger_instances
from boosty_downloader.infrastructure.loggers.debug_file import debug_logging

if TYPE_CHECKING:
    from pathlib import Path

AuthorArgument = Annotated[
    str | None,
    typer.Argument(
        help='Render this creator only; omit for the whole library.',
        metavar='AUTHOR',
        show_default=False,
    ),
]


def _validate_author(author: str | None) -> None:
    if author is None:
        return
    try:
        validate_author_name(author)
    except ValueError as error:
        raise typer.BadParameter(str(error), param_hint='AUTHOR') from error


def _render_pages(root: Path, author: str | None) -> None:
    try:
        store = JsonPostRecords(root)
        report = RenderPostsUseCase(
            library_root=root,
            store=store,
            link_resolver=SavedPageLinkResolver(root, store.find_post),
        ).execute(author=author)
    except (OSError, ValueError, RuntimeError) as error:
        logger_instances.downloader_logger.error(
            render_pages_failure(root=root, reason=str(error))
        )
        point_at_the_debug_log()
        raise typer.Exit(1) from error
    logger_instances.downloader_logger.success(
        render_pages_result(pages=report.pages, root=root)
    )


def register(app: typer.Typer) -> None:
    """Register offline page generation for one creator or the whole library."""

    @app.command('render', short_help='Rebuild saved post pages offline.')
    def render_entrypoint(
        ctx: typer.Context,
        author: AuthorArgument = None,
        *,
        destination_directory: DestinationDirectoryOption = None,
    ) -> None:
        """
        Rebuild every saved post.html without network access or credentials.

        Omit AUTHOR to render the whole library. Pages reflect saved post content and currently available local media. Viewing marks and media files are kept unchanged. The search index is not required. Use -o to select the library; otherwise the target folder from config.yaml applies.
        """
        options = global_options(ctx)
        with report_command_errors(read_only=True):
            _validate_author(author)
            root = resolve_library_root(
                config_path=options.config_path,
                destination_directory=destination_directory,
            )
            check_library_compatibility(root)
        with debug_logging(enabled=options.debug):
            _render_pages(root, author)
