"""The media column shared by the overview, the download plan and the run statistics."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table

if TYPE_CHECKING:
    from boosty_downloader.application.blog_overview import MediaCounts

# Only emoji with East Asian Width "wide": rich measures them as two cells,
# so the column aligns. A text-presentation glyph like 🖼 counts as one
# cell, is drawn as two, and eats the space after it.
_KINDS = (
    ('📷', 'images'),
    ('📄', 'files'),
    ('🎬', 'boosty videos'),
    ('🔗', 'external videos'),
    ('🎵', 'audio'),
)


def _values(counts: MediaCounts) -> tuple[int, int, int, int, int]:
    return (
        counts.images,
        counts.files,
        counts.boosty_videos,
        counts.external_videos,
        counts.audio,
    )


def media_table(counts: MediaCounts) -> Table:
    """One row per media kind, counts right-aligned."""
    table = Table.grid(padding=(0, 2))
    table.add_column()
    table.add_column(justify='right', style='bold')
    for (emoji, name), count in zip(_KINDS, _values(counts), strict=True):
        table.add_row(f'{emoji} {name}', str(count))
    return table


# Short labels for the one-line form: the column has room for full names.
_SHORT_NAMES = ('images', 'files', 'videos', 'external', 'audio')


def media_line(counts: MediaCounts) -> str:
    """Join the counts on one line: '📷 5 images · 📄 17 files · ...'."""
    return ' · '.join(
        f'{emoji} [bold]{count}[/bold] {name}'
        for (emoji, _full), name, count in zip(
            _KINDS, _SHORT_NAMES, _values(counts), strict=True
        )
    )
