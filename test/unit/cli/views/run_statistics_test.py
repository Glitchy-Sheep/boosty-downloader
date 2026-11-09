"""The closing statistics block as the user sees it."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

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
                'Posts: 5 downloaded, 3 already cached, 1 skipped by filters, '
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


@pytest.mark.parametrize('posts_downloaded', [0, 1], ids=['nothing-new', 'downloaded'])
def test_deleted_media_count_and_restore_hint_in_both_summaries(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
    posts_downloaded: int,
) -> None:
    stats = RunStatistics(posts_downloaded=posts_downloaded, media_deleted=2)

    text = plain(render_run_statistics(stats, elapsed_seconds=3))

    shows(
        text,
        [
            'Media deleted from disk: 2',
            'Use --restore-missing to download selected missing media again.',
        ],
    )
    assert text.count('Media deleted from disk:') == 1
    assert text.count('--restore-missing') == 1


@pytest.mark.parametrize('posts_downloaded', [0, 1], ids=['nothing-new', 'downloaded'])
def test_summary_omits_deleted_media_when_none_remain(
    plain: Callable[[RenderableType], str],
    posts_downloaded: int,
) -> None:
    stats = RunStatistics(posts_downloaded=posts_downloaded)

    text = plain(render_run_statistics(stats, elapsed_seconds=3))

    assert 'Media deleted from disk:' not in text
    assert '--restore-missing' not in text
