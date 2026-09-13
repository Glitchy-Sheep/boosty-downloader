"""The check overview as the user sees it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.application.blog_overview import (
    AccessGroup,
    BlogOverview,
    MediaCounts,
    TierStep,
    UnlockCost,
)
from boosty_downloader.cli.views.blog_overview import render_blog_overview

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import RenderableType

_NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
_FREE = UnlockCost(tiers=(), one_off_posts=0, one_off_total=0)


def _overview(**overrides: object) -> BlogOverview:
    """An author's own blog: everything accessible, four ways to unlock."""
    defaults: dict[str, object] = {
        'author_name': 'example_author',
        'total_posts': 11,
        'accessible_posts': 11,
        'access_groups': [
            AccessGroup(tier=None, tier_price=0, post_price=0, posts=1, accessible=1),
            AccessGroup(
                tier='Tester', tier_price=10, post_price=0, posts=2, accessible=2
            ),
            AccessGroup(tier=None, tier_price=0, post_price=100, posts=6, accessible=6),
            AccessGroup(tier=None, tier_price=0, post_price=300, posts=2, accessible=2),
        ],
        'full_access_cost': UnlockCost(
            tiers=(TierStep(tier='Tester', price=10, posts=2),),
            one_off_posts=8,
            one_off_total=1200,
        ),
        'remaining_cost': _FREE,
        'media': MediaCounts(images=11, files=21, boosty_videos=8, audio=2),
        'first_post_at': datetime(2026, 1, 4, tzinfo=timezone.utc),
        'last_post_at': datetime(2026, 8, 21, tzinfo=timezone.utc),
        'locked_post_titles': (),
    }
    return BlogOverview(**{**defaults, **overrides})  # pyright: ignore[reportArgumentType]


def test_own_blog_overview(
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
):
    """The block is the contract with the user: layout and wording are pinned."""
    golden('blog_overview_own', plain(render_blog_overview(_overview(), now=_NOW)))


def test_foreign_blog_with_locked_posts(
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
):
    """Locked counts, the price to unlock the rest and the locked titles."""
    overview = _overview(
        author_name='other_author',
        total_posts=9,
        accessible_posts=3,
        access_groups=[
            AccessGroup(tier=None, tier_price=0, post_price=0, posts=2, accessible=2),
            AccessGroup(
                tier='Follower', tier_price=0, post_price=0, posts=1, accessible=1
            ),
            AccessGroup(
                tier='Regular', tier_price=199, post_price=0, posts=4, accessible=0
            ),
            AccessGroup(
                tier='Regular', tier_price=199, post_price=100, posts=1, accessible=0
            ),
            AccessGroup(tier=None, tier_price=0, post_price=100, posts=1, accessible=0),
        ],
        full_access_cost=UnlockCost(
            tiers=(
                TierStep(tier='Follower', price=0, posts=1),
                TierStep(tier='Regular', price=199, posts=6),
            ),
            one_off_posts=1,
            one_off_total=100,
        ),
        remaining_cost=UnlockCost(
            tiers=(TierStep(tier='Regular', price=199, posts=5),),
            one_off_posts=1,
            one_off_total=100,
        ),
        media=MediaCounts(images=2),
        locked_post_titles=('Стрим [запись]', 'evil [/]', 'plain one'),
    )

    text = plain(render_blog_overview(overview, now=_NOW))

    golden('blog_overview_locked', text)
    # Author text goes through rich markup untouched: no crash, nothing eaten.
    assert 'Стрим [запись]' in text
    assert 'evil [/]' in text


def test_empty_blog(
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
):
    overview = _overview(
        total_posts=0,
        accessible_posts=0,
        access_groups=[],
        full_access_cost=_FREE,
        media=MediaCounts(),
        first_post_at=None,
        last_post_at=None,
    )

    golden('blog_overview_empty', plain(render_blog_overview(overview, now=_NOW)))


@pytest.mark.parametrize(
    ('last_post_at', 'expected'),
    [
        pytest.param(datetime(2026, 9, 13, 9, 0, tzinfo=timezone.utc), 'today'),
        pytest.param(datetime(2026, 9, 12, 23, 0, tzinfo=timezone.utc), 'yesterday'),
        pytest.param(datetime(2026, 9, 10, tzinfo=timezone.utc), '3 days ago'),
    ],
)
def test_last_post_age_speaks_in_calendar_days(
    plain: Callable[[RenderableType], str], last_post_at: datetime, expected: str
):
    overview = _overview(last_post_at=last_post_at)

    assert f'last post {expected}' in plain(render_blog_overview(overview, now=_NOW))


def test_last_post_age_follows_the_users_calendar(
    plain: Callable[[RenderableType], str],
):
    """22:30 UTC yesterday is 01:30 today in UTC+3: say 'today', not 'yesterday'."""
    now = datetime(2026, 9, 13, 2, 0, tzinfo=timezone(timedelta(hours=3)))
    overview = _overview(
        last_post_at=datetime(2026, 9, 12, 22, 30, tzinfo=timezone.utc)
    )

    assert 'last post today' in plain(render_blog_overview(overview, now=now))


def test_single_post_blog_says_post_not_posts(
    plain: Callable[[RenderableType], str],
):
    overview = _overview(total_posts=1, accessible_posts=1)

    assert '1 post, 1 accessible to you' in plain(
        render_blog_overview(overview, now=_NOW)
    )


def test_locked_list_is_capped_and_untitled_posts_are_named(
    plain: Callable[[RenderableType], str],
):
    """A big blog locks hundreds of posts; blank titles must not print as blank lines."""
    titles = (*(f'post {n}' for n in range(22)), '', '   ')
    overview = _overview(accessible_posts=0, locked_post_titles=titles)

    text = plain(render_blog_overview(overview, now=_NOW))

    assert 'Locked posts (24)' in text
    assert '  post 19' in text
    assert '  post 20' not in text
    assert '  and 4 more' in text
    assert '(no title)' not in text, 'the untitled ones sit past the cap here'

    text = plain(
        render_blog_overview(
            _overview(accessible_posts=0, locked_post_titles=('', 'named')), now=_NOW
        )
    )

    assert '  (no title)' in text
    assert '  named' in text


def test_tier_ladder_shows_what_each_rung_opens(
    plain: Callable[[RenderableType], str],
):
    """A gimmick top tier must not hide that the cheap one opens most posts."""
    overview = _overview(
        accessible_posts=12,
        total_posts=91,
        remaining_cost=UnlockCost(
            tiers=(
                TierStep(tier='Regular', price=199, posts=78),
                TierStep(tier='Billionaire', price=99999, posts=79),
            ),
            one_off_posts=0,
            one_off_total=0,
        ),
    )

    # The line is longer than the 80-column render: compare it unwrapped.
    text = ' '.join(plain(render_blog_overview(overview, now=_NOW)).split())

    assert (
        'To unlock the rest: 199 RUB/mo (Regular) opens 78 posts, '
        '99999 RUB/mo (Billionaire) opens all 79'
    ) in text
    assert 'Full access costs' not in text
