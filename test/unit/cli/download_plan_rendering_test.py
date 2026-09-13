"""Tests for the terminal rendering of a download plan."""

from __future__ import annotations

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.download_plan import DownloadPlan
from boosty_downloader.application.filtering import DownloadContentTypeFilter
from boosty_downloader.cli.download_plan_rendering import render_download_plan


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


def test_plan_with_work_renders_counts_media_and_size():
    plan = _plan(
        new_posts=5,
        outdated_posts=2,
        complete_posts=4,
        media=MediaCounts(images=11, files=21, boosty_videos=8, audio=2),
        known_bytes=2048,
        unknown_size_videos=8,
    )

    assert render_download_plan(plan, filters=list(DownloadContentTypeFilter)) == (
        'Download plan (filters: boosty_videos, external_videos, '
        'post_content, files, audio):\n'
        '  New posts: [bold]5[/bold]\n'
        '  Updated or partially downloaded: [bold]2[/bold]\n'
        '  Already complete: [bold]4[/bold]\n'
        '\n'
        'Media to download:\n'
        '  🖼 images: [bold]11[/bold]\n'
        '  📄 files: [bold]21[/bold]\n'
        '  🎬 boosty videos: [bold]8[/bold]\n'
        '  🔗 external videos: [bold]0[/bold]\n'
        '  🎵 audio: [bold]2[/bold]\n'
        '\n'
        'Known download size: [bold]2.00 KB[/bold] (+ 8 videos of unknown size)'
    )


def test_nothing_to_do_says_so_and_hides_the_media_block():
    plan = _plan(complete_posts=7)

    rendered = render_download_plan(plan, filters=[DownloadContentTypeFilter.files])

    assert rendered == (
        'Download plan (filters: files):\n'
        '  New posts: [bold]0[/bold]\n'
        '  Updated or partially downloaded: [bold]0[/bold]\n'
        '  Already complete: [bold]7[/bold]\n'
        '\n'
        'Nothing to download - everything is up to date.'
    )


def test_filtered_out_row_appears_only_when_present():
    plan = _plan(new_posts=1, filtered_out_posts=3, media=MediaCounts(files=1))

    rendered = render_download_plan(plan, filters=[DownloadContentTypeFilter.files])

    assert 'Nothing under these filters: [bold]3[/bold]' in rendered
    assert 'Known download size: [bold]0.00 B[/bold]' in rendered
