"""The --dry-run block: what a download run would fetch."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group
from rich.rule import Rule
from rich.table import Table

from boosty_downloader.cli.views.media import media_table
from boosty_downloader.cli.views.text import plural
from boosty_downloader.infrastructure.human_readable_filesize import (
    human_readable_size,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from rich.console import RenderableType

    from boosty_downloader.application.download_plan import DownloadPlan
    from boosty_downloader.application.filtering import DownloadContentTypeFilter


def render_download_plan(
    plan: DownloadPlan, *, filters: Sequence[DownloadContentTypeFilter]
) -> RenderableType:
    """Build the plan block shown by --dry-run."""
    parts: list[RenderableType] = [
        Rule(title='Download plan', style='dim'),
        'Filters: ' + ', '.join(item.name for item in filters),
        '',
        '[bold]Posts[/bold]',
        _posts_table(plan),
    ]
    if plan.new_posts == 0 and plan.outdated_posts == 0:
        parts += ['', 'Nothing to download - everything is up to date.']
    else:
        parts += [
            '',
            '[bold]Media to download[/bold]',
            media_table(plan.media),
            '',
            _size_line(plan),
        ]
    parts.append(Rule(style='dim'))
    return Group(*parts)


def _posts_table(plan: DownloadPlan) -> Table:
    table = Table.grid(padding=(0, 2))
    table.add_column()
    table.add_column(justify='right', style='bold')
    table.add_row('New', str(plan.new_posts))
    table.add_row('Updated or partially downloaded', str(plan.outdated_posts))
    table.add_row('Already complete', str(plan.complete_posts))
    if plan.filtered_out_posts:
        table.add_row('Nothing under these filters', str(plan.filtered_out_posts))
    return table


def _size_line(plan: DownloadPlan) -> str:
    line = f'Known download size: [bold]{human_readable_size(plan.known_bytes)}[/bold]'
    if plan.unknown_size_videos:
        line += f' (+ {plural(plan.unknown_size_videos, "video")} of unknown size)'
    return line
