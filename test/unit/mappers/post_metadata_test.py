"""Locked observations and live bodies share one complete metadata contract."""

from datetime import datetime, timezone

import pytest
from support.synthetic_post import (
    COMMENTS,
    CONTENT_COUNTS,
    CREATED_AT,
    LIKES,
    POST_ID,
    POST_TITLE,
    TAG_TITLES,
    TIER_NAME,
    TIER_PRICE,
    UPDATED_AT,
    synthetic_post,
)

from boosty_downloader.application.mappers.post_metadata import map_post_metadata
from boosty_downloader.domain.stored_post import PostMetadata
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO

AUTHOR = 'fixture-author'


@pytest.mark.parametrize('has_access', [True, False])
def test_metadata_includes_prices_counts_and_dates_independently_of_access(
    *,
    has_access: bool,
) -> None:
    dto = PostDTO.model_validate({**synthetic_post(), 'hasAccess': has_access})
    before = dto.model_copy(deep=True)

    result = map_post_metadata(dto, AUTHOR)

    assert result == PostMetadata(
        id=POST_ID,
        author=AUTHOR,
        url=f'https://boosty.to/{AUTHOR}/posts/{POST_ID}',
        title=POST_TITLE,
        created_at=datetime.fromtimestamp(CREATED_AT, timezone.utc),
        updated_at=datetime.fromtimestamp(UPDATED_AT, timezone.utc),
        published_at=datetime.fromtimestamp(CREATED_AT, timezone.utc),
        tags=TAG_TITLES,
        tier=TIER_NAME,
        tier_price_rub=TIER_PRICE,
        post_price_rub=0,
        likes=LIKES,
        comments=COMMENTS,
        content_counters=CONTENT_COUNTS,
    )
    result.tags.clear()
    result.content_counters.clear()
    assert dto == before


def test_absent_optional_metadata_does_not_invent_prices_or_counts() -> None:
    dto = PostDTO.model_validate(
        {
            **synthetic_post(),
            'subscriptionLevel': None,
            'currencyPrices': None,
            'tags': None,
            'count': None,
            'contentCounters': None,
            'publishTime': None,
        }
    )

    result = map_post_metadata(dto, AUTHOR)

    assert result.tier is None
    assert result.tier_price_rub is None
    assert result.post_price_rub is None
    assert result.published_at is None
    assert result.tags == []
    assert result.content_counters == {}
    assert result.likes == result.comments == 0


def test_other_currencies_do_not_become_ruble_prices() -> None:
    dto = PostDTO.model_validate(synthetic_post())
    assert dto.subscription_level is not None
    dto.subscription_level.currency_prices = {'USD': 4.0}
    dto.currency_prices = {'USD': 7.0}

    result = map_post_metadata(dto, AUTHOR)

    assert result.tier == TIER_NAME
    assert result.tier_price_rub is None
    assert result.post_price_rub is None
