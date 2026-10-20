"""Post folders retain their identity marker within a portable filename."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from boosty_downloader.domain.post_folder import (
    compose_post_directory_name,
    get_post_id_prefix,
    parse_post_folder_id,
)

CREATED_AT = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def test_long_cyrillic_title_folder_fits_the_byte_limit() -> None:
    """A long Unicode title fits the byte budget and retains the post ID."""
    name = compose_post_directory_name('я' * 300, CREATED_AT, 'a2dd6942-full-uuid')

    assert len(name.encode('utf-8')) <= 240
    assert name.startswith('2026-08-14 - ')
    assert name.endswith(' (a2dd6942)')


def test_same_long_title_posts_get_distinct_folders() -> None:
    """Title truncation preserves the ID that distinguishes same-titled posts."""
    first = compose_post_directory_name('я' * 300, CREATED_AT, 'a2dd6942-first')
    second = compose_post_directory_name('я' * 300, CREATED_AT, 'b3ee7053-second')

    assert first != second


def test_dots_in_title_survive() -> None:
    name = compose_post_directory_name('Release v2.0', CREATED_AT, 'a2dd6942-x')

    assert name == '2026-08-14 - Release v2.0 (a2dd6942)'


def test_empty_title_falls_back_to_a_readable_name() -> None:
    name = compose_post_directory_name('', CREATED_AT, 'a2dd6942-x')

    assert name == '2026-08-14 - No title (a2dd6942)'


@pytest.mark.parametrize(
    ('title', 'expected_title'),
    [
        (' \t\n', 'No title'),
        ('<>:"/\\|?*', 'untitled'),
        ('Cafe\u0301', 'Café'),
        ('CON', 'CON'),
    ],
)
def test_title_cleanup(title: str, expected_title: str) -> None:
    name = compose_post_directory_name(title, CREATED_AT, 'p1')

    assert name == f'2026-08-14 - {expected_title} (p1)'


def test_date_uses_the_supplied_timezone() -> None:
    created_at = datetime(2026, 8, 14, 0, 30, tzinfo=timezone(timedelta(hours=3)))

    name = compose_post_directory_name('Title', created_at, 'p1')

    assert name == '2026-08-14 - Title (p1)'


@pytest.mark.parametrize(
    ('post_id', 'prefix'),
    [('p1', 'p1'), ('Ab_9-xZ7-full-id', 'Ab_9-xZ7'), ('a2dd6942/ю', 'a2dd6942')],
)
def test_folder_identity_uses_only_the_portable_prefix(
    post_id: str, prefix: str
) -> None:
    name = compose_post_directory_name('Title', CREATED_AT, post_id)

    assert get_post_id_prefix(post_id) == prefix
    assert name == f'2026-08-14 - Title ({prefix})'
    assert parse_post_folder_id(name) == prefix


@pytest.mark.parametrize('post_id', ['', 'abc/defg-rest', 'пост1234', 'post id1'])
def test_unrepresentable_identity_prefix_is_rejected(post_id: str) -> None:
    with pytest.raises(ValueError, match='Post ID prefix'):
        get_post_id_prefix(post_id)
    with pytest.raises(ValueError, match='Post ID prefix'):
        compose_post_directory_name('Title', CREATED_AT, post_id)


@pytest.mark.parametrize(('collision', 'counter'), [(1, 2), (2, 3), (99, 100)])
def test_collision_number_precedes_the_final_identity_marker(
    collision: int, counter: int
) -> None:
    name = compose_post_directory_name(
        'Title (draft)', CREATED_AT, 'p1', collision=collision
    )

    assert name == f'2026-08-14 - Title (draft) [{counter}] (p1)'
    assert parse_post_folder_id(name) == 'p1'


@pytest.mark.parametrize('collision', [-1, True, 1.5, 10**240])
def test_invalid_collision_is_rejected(collision: int) -> None:
    with pytest.raises(ValueError, match='Collision count'):
        compose_post_directory_name('Title', CREATED_AT, 'p1', collision=collision)


@pytest.mark.parametrize('title', ['я' * 300, '😀' * 300, 'CON.' + 'x' * 300])
def test_collision_and_reserved_name_prefix_fit_the_byte_budget(title: str) -> None:
    name = compose_post_directory_name(
        title, CREATED_AT, 'a2dd6942-full-id', collision=1
    )

    assert len(name.encode('utf-8')) <= 240
    assert name.endswith(' [2] (a2dd6942)')
    assert parse_post_folder_id(name) == 'a2dd6942'


def test_reserved_name_underscore_fits_without_a_collision() -> None:
    name = compose_post_directory_name(
        'CON.' + 'x' * 300, CREATED_AT, 'a2dd6942-full-id'
    )

    assert len(name.encode('utf-8')) == 240
    assert name.startswith('2026-08-14 - _CON.')
    assert name.endswith(' (a2dd6942)')


@pytest.mark.parametrize(
    ('name', 'prefix'),
    [
        ('2024-02-29 - Title (p1)', 'p1'),
        ('2026-08-14 - Title (old-id) [2] (Ab_9-xZ7)', 'Ab_9-xZ7'),
        ('2026-08-14 - Cafe\u0301 (p1)', 'p1'),
    ],
)
def test_parser_accepts_existing_folder_names(name: str, prefix: str) -> None:
    assert parse_post_folder_id(name) == prefix


def test_parser_accepts_legacy_name_exceeding_generation_budget() -> None:
    name = '2026-08-14 - _CON.' + 'x' * 212 + ' (a2dd6942)'

    assert len(name.encode('utf-8')) == 241
    assert parse_post_folder_id(name) == 'a2dd6942'


@pytest.mark.parametrize(
    'name',
    [
        '2026-02-29 - Title (p1)',
        '2026-13-01 - Title (p1)',
        '0000-01-01 - Title (p1)',
        '2026-8-14 - Title (p1)',
        '２０２６-08-14 - Title (p1)',
        '2026-08-14 -  (p1)',
        '2026-08-14 -    (p1)',
        '2026-08-14 - Title ()',
        '2026-08-14 - Title (123456789)',
        '2026-08-14 - Title (пост)',
        '2026-08-14 - Title (p 1)',
        '2026-08-14 - Title (p1) extra',
        '2026-08-14 - Title (p1)\n',
        '../2026-08-14 - Title (p1)',
        'author/2026-08-14 - Title (p1)',
    ],
)
def test_parser_rejects_malformed_folder_names(name: str) -> None:
    assert parse_post_folder_id(name) is None


@pytest.mark.parametrize('forbidden', ['/', '\\', ':', '?', '\n', '\x00', '\x7f'])
def test_parser_rejects_forbidden_characters_in_the_title(forbidden: str) -> None:
    assert parse_post_folder_id(f'2026-08-14 - A{forbidden}B (p1)') is None
