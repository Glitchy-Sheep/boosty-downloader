"""The check overview as the user sees it."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.application.blog_overview import (
    BlogOverview,
    MediaCounts,
    PostBrief,
    SinglePurchases,
    TierStep,
    TierSummary,
    UnlockCost,
)
from boosty_downloader.cli.views.blog_overview import render_blog_overview

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rich.console import RenderableType

_NOW = datetime(2026, 9, 13, 12, 0, tzinfo=timezone.utc)
_NOTHING = UnlockCost(tiers=(), one_off_posts=0, one_off_total=0)
_NO_SINGLES = SinglePurchases(posts=0, total=0, min_price=0, max_price=0, entries=())


def _brief(
    title: str, day: int, *, accessible: bool = True, price: float = 0
) -> PostBrief:
    return PostBrief(
        title=title,
        created_at=datetime(2026, 8, day, tzinfo=timezone.utc),
        accessible=accessible,
        price=price,
    )


def _overview(**overrides: object) -> BlogOverview:
    """An author's own blog: everything open, one tier, eight posts sold one by one."""
    defaults: dict[str, object] = {
        'author_name': 'example_author',
        'total_posts': 11,
        'accessible_posts': 11,
        'free_posts': 1,
        'free_entries': (_brief('Hello world', 1),),
        'tiers': (
            TierSummary(
                tier='Tester',
                price=10,
                adds=2,
                posts=3,
                purchasable=0,
                min_post_price=0,
                max_post_price=0,
                entries=(_brief('Second tester post', 9), _brief('Tester post', 2)),
            ),
        ),
        'single_purchases': SinglePurchases(
            posts=8,
            total=1200,
            min_price=100,
            max_price=300,
            entries=(_brief('Paid post', 21, price=300),),
        ),
        'your_tier': 'Tester',
        'remaining_cost': _NOTHING,
        'media': MediaCounts(images=11, files=21, boosty_videos=8, audio=2),
        'first_post_at': datetime(2026, 1, 4, tzinfo=timezone.utc),
        'last_post_at': datetime(2026, 8, 21, tzinfo=timezone.utc),
    }
    return BlogOverview(**{**defaults, **overrides})  # pyright: ignore[reportArgumentType]


def _foreign_blog(**overrides: object) -> BlogOverview:
    """A big blog with three tiers, seen by an account without a subscription."""
    defaults: dict[str, object] = {
        'author_name': 'other_author',
        'total_posts': 233,
        'accessible_posts': 75,
        'free_posts': 75,
        'free_entries': (_brief('Open lesson', 20), _brief('Intro', 3)),
        'tiers': (
            TierSummary(
                'First steps',
                397,
                18,
                93,
                14,
                200,
                1000,
                entries=(
                    _brief('Стрим [запись]', 19, accessible=False, price=200),
                    _brief('   ', 4, accessible=False),
                ),
            ),
            TierSummary('Walking', 997, 125, 218, 125, 300, 1000, entries=()),
            TierSummary('Far going', 1499, 12, 230, 12, 1000, 1000, entries=()),
        ),
        'single_purchases': SinglePurchases(
            posts=3,
            total=4000,
            min_price=500,
            max_price=2000,
            entries=(_brief('evil [/]', 5, accessible=False, price=2000),),
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
    }
    return _overview(**{**defaults, **overrides})


def _line_with(text: str, marker: str) -> str:
    return next(line for line in text.splitlines() if marker in line)


def test_own_blog_overview(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
):
    """The block is the contract with the user: layout and wording are pinned."""
    shows(
        plain(render_blog_overview(_overview(), now=_NOW)),
        [
            'boosty.to/example_author',
            '11 posts, 11 accessible to you',
            '2026-01-04 to 2026-08-21, last post 23 days ago',
            'What each tier gives (a higher tier includes the lower ones)',
            'Tier Price Adds Posts Of blog Per post',
            'No tier free - 1 9%',
            'Tester 10 RUB/mo 2 3 27%',
            '✔ Everything + 1200 RUB once 8 11 100% 100-300 RUB',
            'For you: all 11 posts open.',
            (
                'Media in your posts: 📷 11 images · 📄 21 files · 🎬 8 videos · '
                '🔗 0 external · 🎵 2 audio'
            ),
        ],
    )


def test_foreign_blog_overview(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
):
    """The ladder, the share of the blog and the price of the rest."""
    text = plain(render_blog_overview(_foreign_blog(), now=_NOW))

    shows(
        text,
        [
            'boosty.to/other_author',
            '233 posts, 75 accessible to you, 158 locked',
            '✔ No tier free - 75 32%',
            'First steps 397 RUB/mo 18 93 40% 200-1000 RUB (14/18)',
            'Walking 997 RUB/mo 125 218 94% 300-1000 RUB',
            'Far going 1499 RUB/mo 12 230 99% 1000 RUB',
            'Everything + 4000 RUB once 3 233 100% 500-2000 RUB',
            'Media in your posts: 📷 5 images',
        ],
    )
    assert '158 locked' in text
    assert 'Open lesson' not in text, 'post lists are opt-in: they bury the ladder'


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


def test_posts_flag_lists_every_rung_newest_first(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
):
    """Each rung with its posts: date, a lock on what you cannot open, the price."""
    text = plain(render_blog_overview(_foreign_blog(), now=_NOW, show_posts=True))

    shows(
        text,
        [
            'No tier (2 posts)',
            '2026-08-20 Open lesson',
            '2026-08-03 Intro',
            'First steps (2 posts)',
            '2026-08-19 🔒 Стрим [запись] 200 RUB',
            '2026-08-04 🔒 (no title)',
            'Sold one by one (1 post)',
            '2026-08-05 🔒 evil [/] 2000 RUB',
        ],
    )
    assert text.index('Open lesson') < text.index('Intro'), 'newest first'
    # Author text goes through rich markup untouched; blank titles get a name.
    assert '🔒 Стрим [запись]  200 RUB' in text
    assert '🔒 evil [/]  2000 RUB' in text
    assert '🔒 (no title)' in text
    assert 'Walking' in text
    assert 'Walking (' not in text, 'empty rungs are skipped'


def test_empty_blog(
    plain: Callable[[RenderableType], str],
    shows: Callable[[str, Sequence[str]], None],
):
    overview = _overview(
        total_posts=0,
        accessible_posts=0,
        free_posts=0,
        free_entries=(),
        tiers=(),
        single_purchases=_NO_SINGLES,
        your_tier=None,
        media=MediaCounts(),
        first_post_at=None,
        last_post_at=None,
    )

    text = plain(render_blog_overview(overview, now=_NOW))

    shows(text, ['boosty.to/example_author', 'No posts found.'])
    assert 'What each tier gives' not in text


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
        free_entries=(_brief('Only one', 1),),
        tiers=(),
        single_purchases=_NO_SINGLES,
        your_tier=None,
    )

    assert '1 post, 1 accessible to you' in plain(
        render_blog_overview(overview, now=_NOW)
    )
