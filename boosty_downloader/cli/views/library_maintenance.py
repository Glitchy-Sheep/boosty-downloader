"""Readable outcomes for offline library maintenance commands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape

from boosty_downloader.cli.views.text import plural

if TYPE_CHECKING:
    from pathlib import Path


def render_reindex_result(*, authors: int, posts: int, path: Path) -> str:
    """Show the complete rebuild counts and the selected index filename."""
    return (
        f'Rebuilt library index: {plural(authors, "author")}, {plural(posts, "post")}. '
        f'Index: [bold]{escape(str(path))}[/bold]'
    )


def render_reindex_failure(*, path: Path, reason: str) -> str:
    """Keep paths and record errors literal, with a writable-cache remedy."""
    return (
        f'Cannot rebuild library index at {escape(str(path))}: {escape(reason)}. '
        'Check the saved records and cache directory permissions, or use '
        '--cache-dir with a writable local folder.'
    )
