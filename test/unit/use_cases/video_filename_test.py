"""Regression tests for #104: several videos in one post must never share a filename."""

from __future__ import annotations

from boosty_downloader.application.use_cases.download_single_post import (
    _boosty_video_filename,
)
from boosty_downloader.domain.post import PostDataChunkBoostyVideo


def _video(video_id: str, title: str) -> PostDataChunkBoostyVideo:
    return PostDataChunkBoostyVideo(
        id=video_id,
        title=title,
        url='https://example.com/video',
        quality='medium',
    )


def test_videos_with_the_same_title_get_different_filenames() -> None:
    """The #104 collision: same title used to mean same file, last one wins."""
    first = _boosty_video_filename(_video('a2dd6942-7297-4340', 'My stream'))
    second = _boosty_video_filename(_video('b3ee7053-8308-5451', 'My stream'))

    assert first != second
    assert first == 'My stream (a2dd6942)'


def test_empty_title_falls_back_to_video_with_id() -> None:
    """A nameless video must still get a readable, unique filename."""
    assert _boosty_video_filename(_video('a2dd6942-7297', '  ')) == 'video (a2dd6942)'
