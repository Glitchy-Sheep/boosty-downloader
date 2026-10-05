"""Filename components share one byte budget and safety policy."""

from __future__ import annotations

import pytest

from boosty_downloader.infrastructure.path_sanitizer import (
    MAX_NAME_BYTES,
    compose_filename,
)


@pytest.mark.parametrize(
    ('stem', 'extension', 'marker', 'expected'),
    [
        ('a:b?', '.zi?p', '', 'ab.zip'),
        ('???', '.txt', '', 'untitled.txt'),
        ('CON', '.txt', '', '_CON.txt'),
        ('lesson.v1', '.mp4', ' (abcdefgh)', 'lesson.v1 (abcdefgh).mp4'),
        ('и\u0306', '.e\u0301xt', '', 'й.éxt'),
    ],
    ids=['unsafe-characters', 'empty-stem', 'device-name', 'dotted-stem', 'unicode'],
)
def test_components_form_a_safe_filename(
    stem: str,
    extension: str,
    marker: str,
    expected: str,
):
    assert compose_filename(stem, extension=extension, marker=marker) == expected


@pytest.mark.parametrize('stem', ['🔥' * 300, '???', 'CON.' + 'a' * 300])
def test_marker_and_normal_extension_survive_the_shared_byte_budget(stem: str):
    result = compose_filename(stem, extension='.zip', marker=' (abcdefgh-2)')

    assert result.endswith(' (abcdefgh-2).zip')
    assert len(result.encode('utf-8')) <= MAX_NAME_BYTES
    assert result


def test_long_extension_leaves_room_for_a_fallback_stem_and_marker():
    result = compose_filename('???', extension='.' + 'я' * 150, marker=' (abcdefgh-2)')

    assert result.startswith('untitled (abcdefgh-2).')
    assert len(result.encode('utf-8')) <= MAX_NAME_BYTES
    assert result.endswith('я')


def test_windows_device_prefix_fits_even_with_a_long_dotted_stem():
    result = compose_filename('CON.' + 'a' * 300, extension='.txt')

    assert result.startswith('_CON.')
    assert result.endswith('.txt')
    assert len(result.encode('utf-8')) <= MAX_NAME_BYTES
