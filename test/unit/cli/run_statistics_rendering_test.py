"""Tests for the closing statistics block of a download run."""

from __future__ import annotations

import pytest

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.run_statistics import RunStatistics
from boosty_downloader.cli.run_statistics_rendering import render_run_statistics


def test_full_run_renders_posts_media_and_size():
    stats = RunStatistics(
        posts_downloaded=5,
        posts_cached=3,
        posts_without_content=1,
        posts_failed=2,
        posts_locked=4,
        media=MediaCounts(images=11, files=21, boosty_videos=8, audio=2),
        downloaded_bytes=2 * 1024**3,
    )

    assert render_run_statistics(stats, elapsed_seconds=252.4) == (
        'Run finished in [bold]4m 12s[/bold]\n'
        'Posts: [bold]5[/bold] downloaded, 3 already cached, '
        '1 without matching content, [red]2 failed[/red], 4 locked\n'
        'Media downloaded:\n'
        '  🖼 images: [bold]11[/bold]\n'
        '  📄 files: [bold]21[/bold]\n'
        '  🎬 boosty videos: [bold]8[/bold]\n'
        '  🔗 external videos: [bold]0[/bold]\n'
        '  🎵 audio: [bold]2[/bold]\n'
        'Total downloaded: [bold]2.00 GB[/bold]'
    )


def test_run_with_nothing_new_stays_short():
    """A rerun over a cached blog must not print a wall of zeros."""
    stats = RunStatistics(posts_cached=12)

    assert render_run_statistics(stats, elapsed_seconds=12) == (
        'Run finished in [bold]12s[/bold]: nothing new to download\n'
        'Posts: [bold]0[/bold] downloaded, 12 already cached'
    )


@pytest.mark.parametrize(
    ('seconds', 'expected'),
    [
        pytest.param(37.9, '37s', id='seconds'),
        pytest.param(252, '4m 12s', id='minutes'),
        pytest.param(3780, '1h 03m', id='hours'),
    ],
)
def test_duration_reads_like_a_clock(seconds: float, expected: str):
    stats = RunStatistics(posts_downloaded=1)

    assert f'[bold]{expected}[/bold]' in render_run_statistics(
        stats, elapsed_seconds=seconds
    )
