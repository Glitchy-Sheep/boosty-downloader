"""Render the RunStatistics of a download run as terminal text with rich markup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.cli.blog_overview_rendering import media_lines
from boosty_downloader.infrastructure.human_readable_filesize import (
    human_readable_size,
)

if TYPE_CHECKING:
    from boosty_downloader.application.run_statistics import RunStatistics


def render_run_statistics(stats: RunStatistics, *, elapsed_seconds: float) -> str:
    """
    Build the closing block of a download run.

    ``elapsed_seconds`` is injected so the block is testable.
    """
    duration = _format_duration(elapsed_seconds)
    if stats.posts_downloaded == 0 and stats.media == MediaCounts():
        return (
            f'Run finished in [bold]{duration}[/bold]: nothing new to download\n'
            f'Posts: {_posts_line(stats)}'
        )
    return '\n'.join(
        [
            f'Run finished in [bold]{duration}[/bold]',
            f'Posts: {_posts_line(stats)}',
            'Media downloaded:',
            *media_lines(stats.media),
            f'Total downloaded: [bold]{human_readable_size(stats.downloaded_bytes)}[/bold]',
        ]
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


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f'{hours}h {minutes:02d}m'
    if minutes:
        return f'{minutes}m {secs:02d}s'
    return f'{secs}s'
