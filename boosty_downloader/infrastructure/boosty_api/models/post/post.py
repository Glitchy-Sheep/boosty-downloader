"""The module describes the form of a post of a user on boosty.to"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 Pydantic should know this type fully

from pydantic import ValidationError, field_validator

from boosty_downloader.infrastructure.boosty_api.models.base import BoostyBaseDTO
from boosty_downloader.infrastructure.boosty_api.models.post.base_post_data import (
    BasePostData,  # noqa: TC001 Pydantic should know this type fully
)
from boosty_downloader.infrastructure.boosty_api.models.post.subscription_level import (
    SubscriptionLevelDTO,
    TolerantCurrencyPrices,
)


class PostDTO(BoostyBaseDTO):
    """Post on boosty.to which also have data pieces"""

    id: str
    title: str

    @field_validator('title', mode='before')
    @classmethod
    def none_title_to_empty(cls, v: object) -> object:
        if v is None:
            return ''
        return v

    created_at: datetime
    updated_at: datetime
    has_access: bool

    # How the post is unlocked. The tier is None for posts open to everyone
    # and for posts sold one by one. The price is what one post costs in the
    # account's display currency, 0 when it is not sold separately.
    # Overview data only: a missing or malformed value must never fail the
    # post, so both fields default instead of raising.
    subscription_level: SubscriptionLevelDTO | None = None
    price: float = 0
    # The single-purchase price in every currency; carries the stable RUB value.
    currency_prices: TolerantCurrencyPrices = None

    @field_validator('price', mode='before')
    @classmethod
    def none_price_to_zero(cls, v: object) -> object:
        if v is None:
            return 0
        return v

    @field_validator('subscription_level', mode='before')
    @classmethod
    def malformed_level_to_none(cls, v: object) -> object:
        if v is None:
            return None
        try:
            return SubscriptionLevelDTO.model_validate(v)
        except ValidationError:
            return None

    signed_query: str

    data: list[BasePostData]
