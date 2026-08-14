"""Post folder names must fit the FS byte limit without losing the dedup id."""

from __future__ import annotations

from datetime import datetime, timezone

from boosty_downloader.src.application.use_cases.download_single_post import (
    compose_post_directory_name,
)

CREATED_AT = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def test_long_cyrillic_title_folder_fits_the_byte_limit() -> None:
    """#93: a long Cyrillic title used to crash mkdir with File name too long."""
    name = compose_post_directory_name('я' * 300, CREATED_AT, 'a2dd6942-full-uuid')

    assert len(name.encode('utf-8')) <= 240
    assert name.startswith('2026-08-14 - ')
    assert name.endswith(' (a2dd6942)')


def test_same_long_title_posts_get_distinct_folders() -> None:
    """Truncation must not eat the id tail, or same-titled posts collide (#104)."""
    first = compose_post_directory_name('я' * 300, CREATED_AT, 'a2dd6942-first')
    second = compose_post_directory_name('я' * 300, CREATED_AT, 'b3ee7053-second')

    assert first != second


def test_dots_in_title_survive() -> None:
    """The old .replace('.', '') hack mangled titles: 'v2.0' became 'v20'."""
    name = compose_post_directory_name('Release v2.0', CREATED_AT, 'a2dd6942-x')

    assert name == '2026-08-14 - Release v2.0 (a2dd6942)'


def test_empty_title_falls_back_to_a_readable_name() -> None:
    """An untitled post must still get a folder, not Path('') and a crash."""
    name = compose_post_directory_name('', CREATED_AT, 'a2dd6942-x')

    assert name == '2026-08-14 - No title (a2dd6942)'
