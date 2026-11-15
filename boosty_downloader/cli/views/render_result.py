"""Readable outcomes for rebuilding saved post pages."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape

from boosty_downloader.cli.views.text import plural

if TYPE_CHECKING:
    from pathlib import Path


def render_pages_result(*, pages: int, root: Path) -> str:
    """Show how many complete pages were rebuilt in the selected library."""
    return (
        f'Rendered {plural(pages, "page")}. Library: [bold]{escape(str(root))}[/bold]'
    )


def render_pages_failure(*, root: Path, reason: str) -> str:
    """Keep library paths and record errors literal in diagnostic output."""
    return (
        f'Cannot render saved pages in {escape(str(root))}: {escape(reason)}. '
        'Check the saved records and library folder permissions.'
    )
