"""The --dry-run plan as the user sees it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.download_plan import DownloadPlan
from boosty_downloader.cli.views.download_plan import render_download_plan
from boosty_downloader.domain.content_types import DownloadContentTypeFilter

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rich.console import RenderableType


def _plan(**overrides: object) -> DownloadPlan:
    defaults: dict[str, object] = {
        'new_posts': 0,
        'outdated_posts': 0,
        'complete_posts': 0,
        'filtered_out_posts': 0,
        'media': MediaCounts(),
        'known_bytes': 0,
        'unknown_size_videos': 0,
    }
    return DownloadPlan(**{**defaults, **overrides})  # pyright: ignore[reportArgumentType]


def test_plan_with_work(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
):
    plan = _plan(
        new_posts=5,
        outdated_posts=2,
        complete_posts=4,
        media=MediaCounts(images=11, files=21, boosty_videos=8, audio=2),
        known_bytes=2048,
        unknown_size_videos=8,
    )

    text = plain(render_download_plan(plan, filters=list(DownloadContentTypeFilter)))

    shows(
        text,
        [
            'Download plan',
            'Filters: boosty_videos, external_videos, post_content, files, audio',
            'New 5',
            'Updated or partially downloaded 2',
            'Already complete 4',
            'Media to download',
            '📷 images 11',
            '📄 files 21',
            '🎬 boosty videos 8',
            '🔗 external videos 0',
            '🎵 audio 2',
            'Known download size: 2.00 KB (+ 8 videos of unknown size)',
        ],
    )
    assert 'Nothing under these filters' not in text


def test_nothing_to_do_hides_the_media_block(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
):
    """A rerun over a cached blog must not print a wall of zeros."""
    plan = _plan(complete_posts=7)

    text = plain(render_download_plan(plan, filters=[DownloadContentTypeFilter.files]))

    shows(
        text,
        [
            'Filters: files',
            'New 0',
            'Already complete 7',
            'Nothing to download - everything is up to date.',
        ],
    )
    assert 'Media to download' not in text


def test_filtered_out_row_appears_only_when_present(
    plain: Callable[[RenderableType], str],
):
    plan = _plan(new_posts=1, filtered_out_posts=3, media=MediaCounts(files=1))

    text = plain(render_download_plan(plan, filters=[DownloadContentTypeFilter.files]))

    assert 'Nothing under these filters' in text
    assert 'Known download size: 0.00 B' in text
