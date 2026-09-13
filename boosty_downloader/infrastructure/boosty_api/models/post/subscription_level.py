"""Subscription tier a post belongs to, as Boosty attaches it to the post."""

from __future__ import annotations

from typing import Annotated

from pydantic import ValidationError, ValidatorFunctionWrapHandler, WrapValidator

from boosty_downloader.infrastructure.boosty_api.models.base import BoostyBaseDTO


def _none_on_error(value: object, handler: ValidatorFunctionWrapHandler) -> object:
    try:
        return handler(value)
    except ValidationError:
        return None


# Prices per currency code, e.g. {'RUB': 199, 'USD': 2.54}. Overview data
# only: a malformed value becomes None instead of failing the post.
TolerantCurrencyPrices = Annotated[
    dict[str, float] | None,
    WrapValidator(_none_on_error),
]


class SubscriptionLevelDTO(BoostyBaseDTO):
    """Subscription tier that unlocks a post."""

    name: str
    # In the account's display currency (RUB, USD, ... depending on the user).
    price: float
    # The same price in every currency; carries the stable RUB value.
    currency_prices: TolerantCurrencyPrices = None
