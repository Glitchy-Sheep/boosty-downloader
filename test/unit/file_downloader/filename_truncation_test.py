"""Long file names (#93) must not lose what makes them openable or unique."""

from __future__ import annotations

from boosty_downloader.application.use_cases.download_single_post import (
    _boosty_video_filename,
)
from boosty_downloader.domain.post import PostDataChunkBoostyVideo
from boosty_downloader.infrastructure.file_downloader import (
    _app_built_filename,
    _author_filename,
)
from boosty_downloader.infrastructure.path_sanitizer import MAX_NAME_BYTES


def test_author_extension_survives_truncation() -> None:
    """A truncated 'архив...zip' without .zip is a file nothing can open."""
    name = _author_filename('я' * 300 + '.zip')

    assert name.endswith('.zip')
    assert len(name.encode('utf-8')) <= MAX_NAME_BYTES


def test_author_name_stays_intact_when_short() -> None:
    """#75 regression guard: author names must never be rewritten."""
    assert _author_filename('any.appimage') == 'any.appimage'


def test_app_built_name_gets_the_guessed_extension() -> None:
    assert _app_built_filename('clip (a2dd6942)', '.mp4') == 'clip (a2dd6942).mp4'


def test_long_video_title_keeps_id_and_extension() -> None:
    """Truncation must eat neither the dedup id (#104) nor the extension."""
    video = PostDataChunkBoostyVideo(
        id='a2dd6942-full', title='я' * 300, url='u', quality='medium'
    )

    name = _app_built_filename(_boosty_video_filename(video), '.mp4')

    assert name.endswith(' (a2dd6942).mp4')
    assert len(name.encode('utf-8')) <= MAX_NAME_BYTES
