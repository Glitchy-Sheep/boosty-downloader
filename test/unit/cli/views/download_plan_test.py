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
        'updated_posts': 0,
        'unchanged_posts': 0,
        'excluded_posts': 0,
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
        updated_posts=2,
        unchanged_posts=4,
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
            'New records 5',
            'Existing posts to update 2',
            'Existing posts unchanged 4',
            'Media to download',
            '📷 images 11',
            '📄 files 21',
            '🎬 boosty videos 8',
            '🔗 external videos 0',
            '🎵 audio 2',
            'Known download size: 2.00 KB (+ 8 videos of unknown size)',
        ],
    )
    assert 'Excluded by tag' not in text


def test_nothing_to_do_reports_unchanged_posts(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
):
    """Unchanged under the selected types does not claim all media is saved."""
    plan = _plan(unchanged_posts=7)

    text = plain(render_download_plan(plan, filters=[DownloadContentTypeFilter.files]))

    shows(
        text,
        [
            'Filters: files',
            'New records 0',
            'Existing posts unchanged 7',
            'No changes under the selected content types.',
        ],
    )
    assert 'Media to download' in text


def test_filtered_out_row_appears_only_when_present(
    plain: Callable[[RenderableType], str],
):
    plan = _plan(new_posts=1, excluded_posts=3, media=MediaCounts(files=1))

    text = plain(render_download_plan(plan, filters=[DownloadContentTypeFilter.files]))

    assert 'Excluded by tag' in text
    assert 'Known download size: 0.00 B' in text


def test_filtered_posts_do_not_claim_everything_is_cached(
    plain: Callable[[RenderableType], str],
):
    text = plain(render_download_plan(_plan(excluded_posts=2), filters=[]))
    assert 'Excluded by tag' in text
    assert 'No changes under the selected content types.' in text
    assert 'everything is up to date' not in text


def test_new_text_only_post_reports_page_work_without_media(
    plain: Callable[[RenderableType], str],
) -> None:
    text = plain(render_download_plan(_plan(new_posts=1), filters=[]))
    assert 'New records' in text
    assert 'No media downloads planned.' in text
    assert 'No changes under the selected content types.' not in text
