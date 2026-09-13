"""The check overview as the user sees it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.application.blog_overview import (
    BlogOverview,
    MediaCounts,
    SinglePurchases,
    TierStep,
    TierSummary,
    UnlockCost,
)
from boosty_downloader.cli.views.blog_overview import render_blog_overview

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import RenderableType

_NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
_NOTHING = UnlockCost(tiers=(), one_off_posts=0, one_off_total=0)
_NO_SINGLES = SinglePurchases(posts=0, total=0, min_price=0, max_price=0)


def _overview(**overrides: object) -> BlogOverview:
    """An author's own blog: everything open, one tier, eight posts sold one by one."""
    defaults: dict[str, object] = {
        'author_name': 'example_author',
        'total_posts': 11,
        'accessible_posts': 11,
        'free_posts': 1,
        'tiers': (
            TierSummary(
                tier='Tester',
                price=10,
                adds=2,
                posts=3,
                purchasable=0,
                min_post_price=0,
                max_post_price=0,
            ),
        ),
        'single_purchases': SinglePurchases(
            posts=8, total=1200, min_price=100, max_price=300
        ),
        'your_tier': 'Tester',
        'remaining_cost': _NOTHING,
        'media': MediaCounts(images=11, files=21, boosty_videos=8, audio=2),
        'first_post_at': datetime(2026, 1, 4, tzinfo=timezone.utc),
        'last_post_at': datetime(2026, 8, 21, tzinfo=timezone.utc),
        'locked_post_titles': (),
    }
    return BlogOverview(**{**defaults, **overrides})  # pyright: ignore[reportArgumentType]


def _foreign_blog(**overrides: object) -> BlogOverview:
    """A big blog with three tiers, seen by an account without a subscription."""
    defaults: dict[str, object] = {
        'author_name': 'other_author',
        'total_posts': 233,
        'accessible_posts': 75,
        'free_posts': 75,
        'tiers': (
            TierSummary('First steps', 397, 18, 93, 14, 200, 1000),
            TierSummary('Walking', 997, 125, 218, 125, 300, 1000),
            TierSummary('Far going', 1499, 12, 230, 12, 1000, 1000),
        ),
        'single_purchases': SinglePurchases(
            posts=3, total=4000, min_price=500, max_price=2000
        ),
        'your_tier': None,
        'remaining_cost': UnlockCost(
            tiers=(
                TierStep('First steps', 397, 18),
                TierStep('Walking', 997, 143),
                TierStep('Far going', 1499, 155),
            ),
            one_off_posts=3,
            one_off_total=4000,
        ),
        'media': MediaCounts(images=5, files=17, boosty_videos=69, audio=11),
        'locked_post_titles': ('Стрим [запись]', 'evil [/]', '   '),
    }
    return _overview(**{**defaults, **overrides})


def _line_with(text: str, marker: str) -> str:
    return next(line for line in text.splitlines() if marker in line)


def test_own_blog_overview(
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
):
    """The block is the contract with the user: layout and wording are pinned."""
    golden('blog_overview_own', plain(render_blog_overview(_overview(), now=_NOW)))


def test_foreign_blog_overview(
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
):
    """The ladder, the share of the blog and the price of the rest."""
    text = plain(render_blog_overview(_foreign_blog(), now=_NOW))

    golden('blog_overview_locked', text)
    assert '158 locked' in text
    assert 'Locked posts' not in text, 'titles are opt-in: they bury the ladder'


def test_for_you_line_names_what_everything_needs(
    plain: Callable[[RenderableType], str],
):
    text = ' '.join(plain(render_blog_overview(_foreign_blog(), now=_NOW)).split())

    assert (
        'For you: 75 of 233 posts open (32%). '
        'Everything needs 1499 RUB/mo (Far going) + 4000 RUB one-off (3 posts).'
    ) in text


def test_the_checkmark_marks_where_you_stand(
    plain: Callable[[RenderableType], str],
):
    """The highest rung fully open to you carries the mark, nothing else does."""
    own = plain(render_blog_overview(_overview(), now=_NOW))
    assert 'Everything' in _line_with(own, '✔')

    foreign = plain(render_blog_overview(_foreign_blog(), now=_NOW))
    assert 'No tier' in _line_with(foreign, '✔')

    subscriber = _foreign_blog(accessible_posts=218, your_tier='Walking')
    assert 'Walking' in _line_with(
        plain(render_blog_overview(subscriber, now=_NOW)), '✔'
    )


def test_locked_flag_lists_every_title(plain: Callable[[RenderableType], str]):
    """Author text goes through rich markup untouched; blank titles get a name."""
    text = plain(render_blog_overview(_foreign_blog(), now=_NOW, show_locked=True))

    assert 'Locked posts (3)' in text
    assert '  Стрим [запись]' in text
    assert '  evil [/]' in text
    assert '  (no title)' in text


def test_empty_blog(
    plain: Callable[[RenderableType], str], golden: Callable[[str, str], None]
):
    overview = _overview(
        total_posts=0,
        accessible_posts=0,
        free_posts=0,
        tiers=(),
        single_purchases=_NO_SINGLES,
        your_tier=None,
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
    overview = _overview(
        total_posts=1,
        accessible_posts=1,
        free_posts=1,
        tiers=(),
        single_purchases=_NO_SINGLES,
        your_tier=None,
    )

    assert '1 post, 1 accessible to you' in plain(
        render_blog_overview(overview, now=_NOW)
    )
