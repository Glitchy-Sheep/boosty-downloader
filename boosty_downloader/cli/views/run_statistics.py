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
    stats: RunStatistics, *, elapsed_seconds: float, completed: bool = True
) -> RenderableType:
    """
    Build the block printed when a download run ends.

    ``elapsed_seconds`` is injected so the block is testable.
    """
    title = Rule(title=_run_title(elapsed_seconds, completed=completed), style='dim')
    if stats.posts_downloaded == 0 and stats.media == MediaCounts():
        return Group(
            title,
            *_status_lines(stats, completed=completed),
            f'Posts: {_posts_line(stats)}',
            *_deleted_media_lines(stats),
            Rule(style='dim'),
        )
    return Group(
        title,
        *_status_lines(stats, completed=completed),
        f'Posts: {_posts_line(stats)}',
        '',
        '[bold]Media downloaded[/bold]',
        media_table(stats.media),
        '',
        f'Total downloaded: [bold]{human_readable_size(stats.downloaded_bytes)}[/bold]',
        *_deleted_media_lines(stats),
        Rule(style='dim'),
    )


def _run_title(elapsed_seconds: float, *, completed: bool) -> str:
    if completed:
        return f'Run finished in {duration(elapsed_seconds)}'
    return f'Run stopped after {duration(elapsed_seconds)}'


def _status_lines(stats: RunStatistics, *, completed: bool) -> list[str]:
    if not completed:
        return ['Partial results']
    if (
        stats.posts_downloaded == 0
        and stats.media == MediaCounts()
        and stats.posts_failed == 0
        and stats.posts_pending == 0
    ):
        return ['Nothing new to download']
    return []


def _posts_line(stats: RunStatistics) -> str:
    """Only the buckets that happened: a clean run reads as one short phrase."""
    parts = [f'[bold]{stats.posts_downloaded}[/bold] downloaded']
    if stats.posts_cached:
        parts.append(f'{stats.posts_cached} unchanged')
    if stats.posts_pending:
        parts.append(f'{stats.posts_pending} pending page checks')
    if stats.posts_without_content:
        parts.append(f'{stats.posts_without_content} skipped by filters')
    if stats.posts_failed:
        parts.append(f'[red]{stats.posts_failed} failed[/red]')
    if stats.posts_locked:
        parts.append(f'{stats.posts_locked} locked')
    return ', '.join(parts)


def _deleted_media_lines(stats: RunStatistics) -> list[str]:
    if not stats.media_deleted:
        return []
    return [
        f'Media deleted from disk: [bold]{stats.media_deleted}[/bold]',
        'Use --restore-missing to download selected missing media again.',
    ]
