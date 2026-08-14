"""yt-dlp writes '<title>.<ext>' to disk - the title must leave room for both."""

from __future__ import annotations

from boosty_downloader.src.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.src.infrastructure.path_sanitizer import MAX_NAME_BYTES


def test_long_title_leaves_room_for_the_extension() -> None:
    """#93: a long video title used to overflow the FS name limit via yt-dlp."""
    title = ExternalVideosDownloader._sanitize_title('я' * 300)  # noqa: SLF001

    assert len(title.encode('utf-8')) <= MAX_NAME_BYTES - len('.webm')


def test_short_title_keeps_its_safe_subset_policy() -> None:
    """Over-cutting would rename existing videos and break old post.html links."""
    title = ExternalVideosDownloader._sanitize_title('My stream: part 2!')  # noqa: SLF001

    assert title == 'My stream part 2'


def test_emoji_only_title_falls_back_instead_of_a_hidden_file() -> None:
    """An all-emoji title left an empty name: '.mp4' is a hidden file on Unix."""
    title = ExternalVideosDownloader._sanitize_title('🔥🔥🔥')  # noqa: SLF001

    assert title == 'untitled'
