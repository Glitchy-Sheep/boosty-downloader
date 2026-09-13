"""The closing statistics block as the user sees it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.run_statistics import RunStatistics
from boosty_downloader.cli.views.run_statistics import render_run_statistics

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import RenderableType


def test_full_run(
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
):
    stats = RunStatistics(
        posts_downloaded=5,
        posts_cached=3,
        posts_without_content=1,
        posts_failed=2,
        posts_locked=4,
        media=MediaCounts(images=11, files=21, boosty_videos=8, audio=2),
        downloaded_bytes=2 * 1024**3,
    )

    golden(
        'run_statistics_full',
        plain(render_run_statistics(stats, elapsed_seconds=252.4)),
    )


def test_run_with_nothing_new_stays_short(
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
):
    """A rerun over a cached blog must not print a wall of zeros."""
    stats = RunStatistics(posts_cached=12)

    text = plain(render_run_statistics(stats, elapsed_seconds=12))

    golden('run_statistics_nothing', text)
    assert 'Media downloaded' not in text
