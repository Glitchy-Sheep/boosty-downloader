"""Long file names (#93) must not lose what makes them openable or unique."""

from __future__ import annotations

import pytest

from boosty_downloader.infrastructure.file_downloader import (
    _app_built_filename,
    _author_filename,
)
from boosty_downloader.infrastructure.media_filenames import (
    boosty_video_filename,
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
    stem = boosty_video_filename('я' * 300, 'a2dd6942-full')
    name = _app_built_filename(stem, '.mp4')

    assert name.endswith(' (a2dd6942).mp4')
    assert len(name.encode('utf-8')) <= MAX_NAME_BYTES


@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        ('a:b?.zi?p', 'ab.zip'),
        (r'folder\lesson.zip', 'folderlesson.zip'),
    ],
    ids=['colon-is-not-a-drive', 'backslash-is-not-a-directory'],
)
def test_author_names_use_portable_filename_characters(name: str, expected: str):
    assert _author_filename(name) == expected
