"""Tests for the terminal rendering of a blog overview."""

from __future__ import annotations

import io
from datetime import datetime, timedelta, timezone

import pytest
from rich.console import Console

from boosty_downloader.application.blog_overview import (
    AccessGroup,
    BlogOverview,
    MediaCounts,
    UnlockCost,
)
from boosty_downloader.cli.blog_overview_rendering import render_blog_overview

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _overview(**overrides: object) -> BlogOverview:
    free = UnlockCost(tier=None, tier_price=0, one_off_posts=0, one_off_total=0)
    defaults: dict[str, object] = {
        'author_name': 'author',
        'total_posts': 8,
        'accessible_posts': 4,
        'access_groups': [],
        'full_access_cost': free,
        'remaining_cost': free,
        'media': MediaCounts(),
        'first_post_at': datetime(2023, 5, 12, tzinfo=timezone.utc),
        'last_post_at': datetime(2026, 8, 19, tzinfo=timezone.utc),
        'locked_post_titles': (),
    }
    return BlogOverview(**{**defaults, **overrides})  # pyright: ignore[reportArgumentType]


def test_full_overview_renders_every_block_in_order():
    """The user reads this block as-is: shape and wording are the contract."""
    overview = _overview(
        access_groups=[
            AccessGroup(tier=None, tier_price=0, post_price=0, posts=2, accessible=2),
            AccessGroup(
                tier='Follower', tier_price=0, post_price=0, posts=1, accessible=1
            ),
            AccessGroup(
                tier='Tester', tier_price=10, post_price=0, posts=2, accessible=0
            ),
            AccessGroup(tier=None, tier_price=0, post_price=100, posts=2, accessible=1),
        ],
        media=MediaCounts(images=11, files=21, boosty_videos=8, audio=2),
        locked_post_titles=('secret post', 'another one'),
    )

    assert render_blog_overview(overview, now=_NOW) == (
        'Blog overview: [bold]8[/bold] posts, [bold]4[/bold] accessible to you\n'
        '\n'
        'Access:\n'
        '  Free: [bold]2[/bold] posts\n'
        '  Follower (free tier): [bold]1[/bold] post\n'
        '  Tester (10 RUB/mo): [bold]2[/bold] posts ([red]2 locked[/red])\n'
        '  Single purchase (100 RUB): [bold]2[/bold] posts ([red]1 locked[/red])\n'
        '\n'
        'Media in accessible posts:\n'
        '  🖼 images: [bold]11[/bold]\n'
        '  📄 files: [bold]21[/bold]\n'
        '  🎬 boosty videos: [bold]8[/bold]\n'
        '  🔗 external videos: [bold]0[/bold]\n'
        '  🎵 audio: [bold]2[/bold]\n'
        '\n'
        'Posts from [bold]2023-05-12[/bold] to [bold]2026-08-19[/bold] '
        '(last post 3 days ago)\n'
        '\n'
        'Locked posts (2):\n'
        '  - secret post\n'
        '  - another one'
    )


def test_tier_sold_one_off_names_both_prices():
    overview = _overview(
        access_groups=[
            AccessGroup(
                tier='Tester', tier_price=10, post_price=100, posts=1, accessible=1
            ),
        ],
    )

    rendered = render_blog_overview(overview, now=_NOW)

    assert '  Tester (10 RUB/mo), or 100 RUB one-off: [bold]1[/bold] post' in rendered


@pytest.mark.parametrize(
    ('last_post_at', 'expected'),
    [
        pytest.param(datetime(2026, 8, 22, 9, 0, tzinfo=timezone.utc), 'today'),
        pytest.param(datetime(2026, 8, 21, 23, 0, tzinfo=timezone.utc), 'yesterday'),
        pytest.param(datetime(2026, 8, 19, tzinfo=timezone.utc), '3 days ago'),
    ],
)
def test_last_post_age_speaks_in_calendar_days(last_post_at: datetime, expected: str):
    overview = _overview(last_post_at=last_post_at)

    assert f'(last post {expected})' in render_blog_overview(overview, now=_NOW)


def test_empty_blog_renders_one_honest_line():
    overview = _overview(
        total_posts=0,
        accessible_posts=0,
        first_post_at=None,
        last_post_at=None,
    )

    assert render_blog_overview(overview, now=_NOW) == 'No posts found.'


def test_fractional_price_keeps_two_digits():
    overview = _overview(
        access_groups=[
            AccessGroup(
                tier='Odd', tier_price=9.5, post_price=0, posts=1, accessible=1
            ),
        ],
    )

    assert 'Odd (9.50 RUB/mo)' in render_blog_overview(overview, now=_NOW)


def test_author_text_cannot_break_rich_markup():
    """A title like '[/]' crashed rich; '[запись]' silently vanished."""
    overview = _overview(
        access_groups=[
            AccessGroup(
                tier='[red]Tier[/]', tier_price=10, post_price=0, posts=1, accessible=0
            ),
        ],
        locked_post_titles=('Стрим [запись]', 'evil [/]'),
    )

    rendered = render_blog_overview(overview, now=_NOW)

    # Printing through a real markup-enabled console is the actual contract.
    console = Console(file=io.StringIO(), markup=True, width=200)
    console.print(rendered)
    text = console.file.getvalue()
    assert 'Стрим [запись]' in text
    assert 'evil [/]' in text
    assert '[red]Tier[/]' in text


def test_last_post_age_follows_the_users_calendar():
    """22:30 UTC yesterday is 01:30 today in UTC+3: say 'today', not 'yesterday'."""
    now = datetime(2026, 8, 22, 2, 0, tzinfo=timezone(timedelta(hours=3)))
    overview = _overview(
        last_post_at=datetime(2026, 8, 21, 22, 30, tzinfo=timezone.utc)
    )

    assert '(last post today)' in render_blog_overview(overview, now=now)


def test_single_post_blog_says_post_not_posts():
    overview = _overview(total_posts=1, accessible_posts=1)

    header = render_blog_overview(overview, now=_NOW).splitlines()[0]

    assert header.startswith('Blog overview: [bold]1[/bold] post,')


def test_absurd_price_does_not_crash_the_overview():
    """DTO validation lets inf through; rendering must survive it."""
    overview = _overview(
        access_groups=[
            AccessGroup(
                tier='Broken',
                tier_price=float('inf'),
                post_price=0,
                posts=1,
                accessible=1,
            ),
        ],
    )

    assert 'Broken' in render_blog_overview(overview, now=_NOW)
