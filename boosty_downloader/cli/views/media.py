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


def media_table(counts: MediaCounts) -> Table:
    """One row per media kind, counts right-aligned."""
    table = Table.grid(padding=(0, 2))
    table.add_column()
    table.add_column(justify='right', style='bold')
    values = (
        counts.images,
        counts.files,
        counts.boosty_videos,
        counts.external_videos,
        counts.audio,
    )
    for (emoji, name), count in zip(_KINDS, values, strict=True):
        table.add_row(f'{emoji} {name}', str(count))
    return table
