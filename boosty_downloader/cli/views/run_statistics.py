"""The closing block of a download run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group
from rich.rule import Rule

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.cli.views.media import media_table
from boosty_downloader.cli.views.text import duration
from boosty_downloader.infrastructure.human_readable_filesize import (
    human_readable_size,
)

if TYPE_CHECKING:
    from rich.console import RenderableType

    from boosty_downloader.application.run_statistics import RunStatistics


def render_run_statistics(
    stats: RunStatistics, *, elapsed_seconds: float
) -> RenderableType:
    """
    Build the block printed when a download run ends.

    ``elapsed_seconds`` is injected so the block is testable.
    """
    title = Rule(title=f'Run finished in {duration(elapsed_seconds)}', style='dim')
    if stats.posts_downloaded == 0 and stats.media == MediaCounts():
        return Group(
            title,
            'Nothing new to download',
            f'Posts: {_posts_line(stats)}',
            Rule(style='dim'),
        )
    return Group(
        title,
        f'Posts: {_posts_line(stats)}',
        '',
        '[bold]Media downloaded[/bold]',
        media_table(stats.media),
        '',
        f'Total downloaded: [bold]{human_readable_size(stats.downloaded_bytes)}[/bold]',
        Rule(style='dim'),
    )


def _posts_line(stats: RunStatistics) -> str:
    """Only the buckets that happened: a clean run reads as one short phrase."""
    parts = [f'[bold]{stats.posts_downloaded}[/bold] downloaded']
    if stats.posts_cached:
        parts.append(f'{stats.posts_cached} already cached')
    if stats.posts_without_content:
        parts.append(f'{stats.posts_without_content} without matching content')
    if stats.posts_failed:
        parts.append(f'[red]{stats.posts_failed} failed[/red]')
    if stats.posts_locked:
        parts.append(f'{stats.posts_locked} locked')
    return ', '.join(parts)
