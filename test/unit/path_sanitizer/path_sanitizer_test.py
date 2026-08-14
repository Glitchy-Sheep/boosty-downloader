"""Post titles become directory and file names - the OS must accept them."""

from __future__ import annotations

import pytest

from boosty_downloader.src.infrastructure.path_sanitizer import (
    MAX_NAME_BYTES,
    sanitize_filename,
)


def test_long_cyrillic_title_fits_the_byte_limit() -> None:
    """#93: 130 Cyrillic chars are 260 bytes - over the 255-byte FS limit."""
    result = sanitize_filename('я' * 130)

    assert len(result.encode('utf-8')) <= MAX_NAME_BYTES


def test_truncation_keeps_the_dedup_suffix() -> None:
    """Truncating the tail would eat the post id and revive #104 collisions."""
    result = sanitize_filename('я' * 300, suffix=' (a2dd6942)')

    assert result.endswith(' (a2dd6942)')
    assert len(result.encode('utf-8')) <= MAX_NAME_BYTES


def test_truncation_keeps_the_extension() -> None:
    """A long author filename must stay openable: archive.zip, not a stub."""
    result = sanitize_filename('я' * 300, suffix='.zip')

    assert result.endswith('.zip')
    assert len(result.encode('utf-8')) <= MAX_NAME_BYTES


def test_truncation_never_splits_a_multibyte_char() -> None:
    """A cut inside an emoji would leave invalid UTF-8 the OS rejects."""
    result = sanitize_filename('🔥🔥🔥', max_bytes=10)

    assert result == '🔥🔥'


def test_newlines_and_control_chars_are_removed() -> None:
    """The PR #86 repro title has newlines - illegal on Windows."""
    result = sanitize_filename('Первая строка\nвторая\tи ещё')

    assert '\n' not in result
    assert '\t' not in result


@pytest.mark.parametrize(
    ('name', 'suffix', 'expected'),
    [
        ('CON', '.txt', '_CON.txt'),
        ('nul', '', '_nul'),
    ],
)
def test_windows_reserved_name_gets_a_prefix(
    name: str, suffix: str, expected: str
) -> None:
    """Windows refuses CON/NUL even with an extension - the file never saves."""
    assert sanitize_filename(name, suffix=suffix) == expected


def test_trailing_dots_and_spaces_are_stripped() -> None:
    """Windows silently drops them, so the name on disk differs from links."""
    assert sanitize_filename('Название поста... ') == 'Название поста'


def test_empty_result_falls_back_to_placeholder() -> None:
    """A title of pure unsafe chars would give Path('') and crash mkdir."""
    assert sanitize_filename('???***') == 'untitled'


def test_decomposed_unicode_is_normalized_to_nfc() -> None:
    """macOS gives decomposed names; NFC keeps names identical across OSes."""
    assert sanitize_filename('\u0438\u0306') == '\u0439'


def test_normal_title_is_unchanged() -> None:
    """Over-cutting would rename every existing folder and re-download all."""
    assert sanitize_filename('My post 2.0 (final)') == 'My post 2.0 (final)'
