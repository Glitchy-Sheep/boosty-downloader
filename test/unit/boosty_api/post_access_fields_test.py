"""The access fields of a post are optional: a listing without them must still parse."""

from __future__ import annotations

import pytest

from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.post.subscription_level import (
    SubscriptionLevelDTO,
)

_BARE_POST: dict[str, object] = {
    'id': 'p1',
    'title': 't',
    'createdAt': 1750000000,
    'updatedAt': 1750000000,
    'hasAccess': True,
    'signedQuery': '',
    'data': [],
}


@pytest.mark.parametrize(
    ('access_fields', 'expected_tier', 'expected_price'),
    [
        pytest.param({}, None, 0, id='fields-absent'),
        pytest.param({'subscriptionLevel': None, 'price': 0}, None, 0, id='free-post'),
        pytest.param(
            {'subscriptionLevel': None, 'price': 100}, None, 100, id='single-purchase'
        ),
        pytest.param(
            {
                'subscriptionLevel': {
                    'id': 1,
                    'name': 'Tester',
                    'price': 10,
                    'currencyPrices': {'RUB': 10, 'USD': 0.1},
                },
                'price': 0,
            },
            SubscriptionLevelDTO(
                name='Tester', price=10, currency_prices={'RUB': 10, 'USD': 0.1}
            ),
            0,
            id='tier-post',
        ),
        pytest.param({'price': None}, None, 0, id='null-price-defaults'),
        pytest.param(
            {'subscriptionLevel': {'id': 1, 'deleted': True}},
            None,
            0,
            id='malformed-tier-drops-to-none',
        ),
        pytest.param(
            {
                'subscriptionLevel': {
                    'name': 'Tester',
                    'price': 10,
                    'currencyPrices': 'not-a-map',
                }
            },
            SubscriptionLevelDTO(name='Tester', price=10, currency_prices=None),
            0,
            id='malformed-currency-map-drops-to-none',
        ),
    ],
)
def test_access_fields_parse_or_default(
    access_fields: dict[str, object],
    expected_tier: SubscriptionLevelDTO | None,
    expected_price: float,
):
    post = PostDTO.model_validate({**_BARE_POST, **access_fields})

    assert post.subscription_level == expected_tier
    assert post.price == expected_price
