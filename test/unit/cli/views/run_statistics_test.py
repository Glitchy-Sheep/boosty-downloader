"""The closing statistics block as the user sees it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.run_statistics import RunStatistics
from boosty_downloader.cli.views.run_statistics import render_run_statistics

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rich.console import RenderableType


def test_full_run(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
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

    shows(
        plain(render_run_statistics(stats, elapsed_seconds=252.4)),
        [
            'Run finished in 4m 12s',
            (
                'Posts: 5 downloaded, 3 already cached, 1 without matching content, '
                '2 failed, 4 locked'
            ),
            'Media downloaded',
            '📷 images 11',
            '📄 files 21',
            '🎬 boosty videos 8',
            '🔗 external videos 0',
            '🎵 audio 2',
            'Total downloaded: 2.00 GB',
        ],
    )


def test_run_with_nothing_new_stays_short(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
):
    """A rerun over a cached blog must not print a wall of zeros."""
    stats = RunStatistics(posts_cached=12)

    text = plain(render_run_statistics(stats, elapsed_seconds=12))

    shows(
        text,
        [
            'Run finished in 12s',
            'Nothing new to download',
            'Posts: 0 downloaded, 12 already cached',
        ],
    )
    assert 'Media downloaded' not in text
