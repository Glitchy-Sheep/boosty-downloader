"""Tests for the blog overview built from a post listing."""

from __future__ import annotations

from datetime import datetime, timezone

from boosty_downloader.application.blog_overview import (
    MediaCounts,
    PostBrief,
    SinglePurchases,
    TierStep,
    UnlockCost,
    summarize_posts,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataAudioDTO,
    BoostyPostDataExternalVideoDTO,
    BoostyPostDataFileDTO,
    BoostyPostDataImageDTO,
    BoostyPostDataOkVideoDTO,
    BoostyPostDataTextDTO,
)
from boosty_downloader.infrastructure.boosty_api.models.post.subscription_level import (
    SubscriptionLevelDTO,
)

_DAY = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _post(  # noqa: PLR0913 - one knob per overview input keeps the cases readable
    post_id: str,
    *,
    has_access: bool = True,
    tier: tuple[str, float] | None = None,
    price: float = 0,
    created_at: datetime = _DAY,
    data: list[object] | None = None,
) -> PostDTO:
    return PostDTO.model_validate(
        {
            'id': post_id,
            'title': f'post {post_id}',
            'createdAt': created_at,
            'updatedAt': created_at,
            'hasAccess': has_access,
            'subscriptionLevel': (
                SubscriptionLevelDTO(name=tier[0], price=tier[1]) if tier else None
            ),
            'price': price,
            'signedQuery': '',
            'data': data or [],
        }
    )


def test_tiers_form_a_ladder_with_cumulative_posts_and_per_post_prices():
    """Tiers nest: `posts` counts the free posts and every lower tier too."""
    posts = [
        _post('free-1'),
        _post('free-2'),
        _post('tester-1', tier=('Tester', 10)),
        _post('tester-2', tier=('Tester', 10), price=50),
        _post('pro', has_access=False, tier=('Pro', 300), price=100),
        _post('single-100', price=100),
        _post('single-300', has_access=False, price=300),
    ]

    overview = summarize_posts('author', posts)

    assert overview.free_posts == 2
    assert [
        (t.tier, t.price, t.adds, t.posts, t.purchasable, t.min_post_price)
        for t in overview.tiers
    ] == [('Tester', 10, 2, 4, 1, 50), ('Pro', 300, 1, 5, 1, 100)]
    singles = overview.single_purchases
    assert (singles.posts, singles.total, singles.min_price, singles.max_price) == (
        2,
        400,
        100,
        300,
    )
    assert overview.your_tier == 'Tester'


def test_every_rung_lists_its_posts_newest_first():
    """The --posts listing: each post sits on exactly one rung, newest on top."""
    day = datetime(2026, 3, 1, tzinfo=timezone.utc)
    later = datetime(2026, 3, 5, tzinfo=timezone.utc)
    posts = [
        _post('free-old', created_at=day),
        _post('free-new', created_at=later),
        _post('tester', tier=('Tester', 10), price=50, created_at=day),
        _post('single', has_access=False, price=300, created_at=day),
    ]

    overview = summarize_posts('author', posts)

    assert overview.free_entries == (
        PostBrief(title='post free-new', created_at=later, accessible=True, price=0),
        PostBrief(title='post free-old', created_at=day, accessible=True, price=0),
    )
    assert overview.tiers[0].entries == (
        PostBrief(title='post tester', created_at=day, accessible=True, price=50),
    )
    assert overview.single_purchases.entries == (
        PostBrief(title='post single', created_at=day, accessible=False, price=300),
    )


def test_your_tier_is_the_highest_fully_open_one():
    both_open = [_post('t', tier=('Tester', 10)), _post('p', tier=('Pro', 300))]
    none_open = [
        _post('t', has_access=False, tier=('Tester', 10)),
        _post('p', has_access=False, tier=('Pro', 300)),
    ]

    assert summarize_posts('author', both_open).your_tier == 'Pro'
    assert summarize_posts('author', none_open).your_tier is None


def test_remaining_cost_is_a_tier_ladder_plus_every_single_purchase():
    """Only what this account cannot open yet, rung by rung."""
    posts = [
        _post('tester', tier=('Tester', 10)),
        _post('pro', has_access=False, tier=('Pro', 300)),
        _post('single-100-b', has_access=False, price=100),
        _post('single-300', has_access=False, price=300),
        # Covered by the Pro subscription: not a one-off purchase.
        _post('tier-and-price', has_access=False, tier=('Tester', 10), price=50),
    ]

    overview = summarize_posts('author', posts)

    assert overview.remaining_cost == UnlockCost(
        tiers=(
            TierStep(tier='Tester', price=10, posts=1),
            TierStep(tier='Pro', price=300, posts=2),
        ),
        one_off_posts=2,
        one_off_total=400,
    )


def test_free_blog_needs_nothing():
    overview = summarize_posts('author', [_post('a'), _post('b')])

    assert overview.remaining_cost.is_free
    assert overview.tiers == ()
    assert overview.free_posts == 2


def test_locked_free_tier_is_still_a_subscription_to_get():
    """A followers-only post costs nothing but does need the (free) tier."""
    overview = summarize_posts(
        'author', [_post('followers', has_access=False, tier=('Follower', 0))]
    )

    assert overview.remaining_cost == UnlockCost(
        tiers=(TierStep(tier='Follower', price=0, posts=1),),
        one_off_posts=0,
        one_off_total=0,
    )
    assert not overview.remaining_cost.is_free


def test_media_is_counted_by_kind_and_only_in_accessible_posts():
    """A locked post shows a teaser: its media must not inflate the counts."""
    ok_video = BoostyPostDataOkVideoDTO.model_validate(
        {
            'type': 'ok_video',
            'id': 'v1',
            'title': 'clip',
            'failoverHost': 'x',
            'duration': 1,
            'complete': True,
            'playerUrls': [],
        }
    )
    audio = BoostyPostDataAudioDTO.model_validate(
        {
            'type': 'audio_file',
            'id': 'a1',
            'url': 'u',
            'title': 'song',
            'size': 1,
            'complete': True,
            'timeCode': 0,
            'showViewsCounter': False,
            'uploadStatus': None,
            'viewsCounter': 0,
        }
    )
    image = BoostyPostDataImageDTO(type='image', url='u')
    accessible_post = _post(
        'open',
        data=[
            BoostyPostDataTextDTO(type='text', content='', modificator=''),
            image,
            image,
            BoostyPostDataFileDTO(type='file', url='u', title='f'),
            ok_video,
            BoostyPostDataExternalVideoDTO(type='video', url='u'),
            audio,
        ],
    )
    locked_post = _post('locked', has_access=False, data=[image])

    overview = summarize_posts('author', [accessible_post, locked_post])

    assert overview.media == MediaCounts(
        images=2, files=1, boosty_videos=1, external_videos=1, audio=1
    )


def test_date_range_does_not_depend_on_listing_order():
    """The API lists newest first; the range must still be min..max."""
    newest = datetime(2026, 8, 20, tzinfo=timezone.utc)
    oldest = datetime(2023, 5, 12, tzinfo=timezone.utc)
    posts = [
        _post('new', created_at=newest),
        _post('mid', created_at=datetime(2025, 1, 1, tzinfo=timezone.utc)),
        _post('old', created_at=oldest),
    ]

    overview = summarize_posts('author', posts)

    assert (overview.first_post_at, overview.last_post_at) == (oldest, newest)


def test_empty_listing_gives_an_empty_overview():
    overview = summarize_posts('author', [])

    assert overview.total_posts == 0
    assert overview.tiers == ()
    assert overview.single_purchases == SinglePurchases(
        posts=0, total=0, min_price=0, max_price=0, entries=()
    )
    assert overview.your_tier is None
    assert overview.media == MediaCounts()
    assert (overview.first_post_at, overview.last_post_at) == (None, None)


def test_prices_group_by_the_stable_rub_value():
    """A USD-display account must not split or mislabel the same tier."""
    post = PostDTO.model_validate(
        {
            'id': 'usd',
            'title': 'post usd',
            'createdAt': _DAY,
            'updatedAt': _DAY,
            'hasAccess': False,
            'subscriptionLevel': {
                'name': 'Regular',
                'price': 2.54,
                'currencyPrices': {'RUB': 199, 'EUR': 2.18, 'USD': 2.54},
            },
            'price': 1.28,
            'currencyPrices': {'RUB': 100, 'EUR': 1.1, 'USD': 1.28},
            'signedQuery': '',
            'data': [],
        }
    )

    overview = summarize_posts('author', [post])

    (tier,) = overview.tiers
    assert (tier.tier, tier.price, tier.purchasable, tier.min_post_price) == (
        'Regular',
        199,
        1,
        100,
    )
    assert tier.entries[0].price == 100
