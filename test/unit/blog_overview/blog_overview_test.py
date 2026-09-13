"""Tests for the blog overview built from a post listing."""

from __future__ import annotations

from datetime import datetime, timezone

from boosty_downloader.application.blog_overview import (
    AccessGroup,
    MediaCounts,
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


def test_posts_group_by_the_way_they_unlock_in_display_order():
    """Free first, tiers by price, single purchases last - each with its own counts."""
    posts = [
        _post('single-300', has_access=False, price=300),
        _post('tester-1', has_access=False, tier=('Tester', 10)),
        _post('free-1'),
        _post('single-100-bought', price=100),
        _post('tester-2', has_access=False, tier=('Tester', 10)),
        _post('follower', tier=('Follower', 0)),
        _post('free-2'),
        _post('single-100-locked', has_access=False, price=100),
    ]

    overview = summarize_posts(posts)

    assert overview.total_posts == 8
    assert overview.accessible_posts == 4
    assert overview.locked_post_titles == (
        'post single-300',
        'post tester-1',
        'post tester-2',
        'post single-100-locked',
    )
    assert overview.access_groups == [
        AccessGroup(tier=None, tier_price=0, post_price=0, posts=2, accessible=2),
        AccessGroup(tier='Follower', tier_price=0, post_price=0, posts=1, accessible=1),
        AccessGroup(tier='Tester', tier_price=10, post_price=0, posts=2, accessible=0),
        AccessGroup(tier=None, tier_price=0, post_price=100, posts=2, accessible=1),
        AccessGroup(tier=None, tier_price=0, post_price=300, posts=1, accessible=0),
    ]


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

    overview = summarize_posts([accessible_post, locked_post])

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

    overview = summarize_posts(posts)

    assert (overview.first_post_at, overview.last_post_at) == (oldest, newest)


def test_empty_listing_gives_an_empty_overview():
    overview = summarize_posts([])

    assert overview.total_posts == 0
    assert overview.access_groups == []
    assert overview.media == MediaCounts()
    assert (overview.first_post_at, overview.last_post_at) == (None, None)
    assert overview.locked_post_titles == ()


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

    overview = summarize_posts([post])

    assert overview.access_groups == [
        AccessGroup(
            tier='Regular', tier_price=199, post_price=100, posts=1, accessible=0
        ),
    ]
