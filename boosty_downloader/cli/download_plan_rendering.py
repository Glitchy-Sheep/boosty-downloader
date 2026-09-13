"""Render a DownloadPlan as terminal text with rich markup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.cli.blog_overview_rendering import media_lines
from boosty_downloader.infrastructure.human_readable_filesize import (
    human_readable_size,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from boosty_downloader.application.download_plan import DownloadPlan
    from boosty_downloader.application.filtering import DownloadContentTypeFilter


def render_download_plan(
    plan: DownloadPlan, *, filters: Sequence[DownloadContentTypeFilter]
) -> str:
    """Build the "what a run would fetch" block shown by --dry-run."""
    filters_label = ', '.join(item.name for item in filters)
    lines = [
        f'Download plan (filters: {filters_label}):',
        f'  New posts: [bold]{plan.new_posts}[/bold]',
        f'  Updated or partially downloaded: [bold]{plan.outdated_posts}[/bold]',
        f'  Already complete: [bold]{plan.complete_posts}[/bold]',
    ]
    if plan.filtered_out_posts:
        lines.append(
            f'  Nothing under these filters: [bold]{plan.filtered_out_posts}[/bold]'
        )
    if plan.new_posts == 0 and plan.outdated_posts == 0:
        lines += ['', 'Nothing to download - everything is up to date.']
        return '\n'.join(lines)
    lines += [
        '',
        'Media to download:',
        *media_lines(plan.media),
        '',
        _size_line(plan),
    ]
    return '\n'.join(lines)


def _size_line(plan: DownloadPlan) -> str:
    known = human_readable_size(plan.known_bytes)
    if plan.unknown_size_videos:
        return (
            f'Known download size: [bold]{known}[/bold] '
            f'(+ {plan.unknown_size_videos} videos of unknown size)'
        )
    return f'Known download size: [bold]{known}[/bold]'
