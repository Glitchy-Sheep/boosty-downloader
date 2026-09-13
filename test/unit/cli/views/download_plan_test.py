"""The --dry-run plan as the user sees it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.download_plan import DownloadPlan
from boosty_downloader.application.filtering import DownloadContentTypeFilter
from boosty_downloader.cli.views.download_plan import render_download_plan

if TYPE_CHECKING:
    from collections.abc import Callable

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
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
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

    golden('download_plan_full', text)
    assert 'Nothing under these filters' not in text


def test_nothing_to_do_hides_the_media_block(
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
):
    """A rerun over a cached blog must not print a wall of zeros."""
    plan = _plan(complete_posts=7)

    text = plain(render_download_plan(plan, filters=[DownloadContentTypeFilter.files]))

    golden('download_plan_nothing', text)
    assert 'Media to download' not in text


def test_filtered_out_row_appears_only_when_present(
    plain: Callable[[RenderableType], str],
):
    plan = _plan(new_posts=1, filtered_out_posts=3, media=MediaCounts(files=1))

    text = plain(render_download_plan(plan, filters=[DownloadContentTypeFilter.files]))

    assert 'Nothing under these filters' in text
    assert 'Known download size: 0.00 B' in text
