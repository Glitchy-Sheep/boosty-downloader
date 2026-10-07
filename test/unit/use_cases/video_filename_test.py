"""Regression tests for #104: several videos in one post must never share a filename."""

from __future__ import annotations

from boosty_downloader.infrastructure.media_filenames import (
    boosty_video_filename,
)


def test_videos_with_the_same_title_get_different_filenames() -> None:
    """The #104 collision: same title used to mean same file, last one wins."""
    first = boosty_video_filename('My stream', 'a2dd6942-7297-4340')
    second = boosty_video_filename('My stream', 'b3ee7053-8308-5451')

    assert first != second
    assert first == 'My stream (a2dd6942)'


def test_empty_title_falls_back_to_video_with_id() -> None:
    """A nameless video must still get a readable, unique filename."""
    assert boosty_video_filename('  ', 'a2dd6942-7297') == 'video (a2dd6942)'
