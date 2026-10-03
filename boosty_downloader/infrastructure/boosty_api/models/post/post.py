"""The module describes the form of a post of a user on boosty.to"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import ValidationError, WrapValidator, field_validator

from boosty_downloader.infrastructure.boosty_api.models.base import (
    BoostyBaseDTO,
    none_on_error,
)
from boosty_downloader.infrastructure.boosty_api.models.post.base_post_data import (
    BasePostData,  # noqa: TC001 Pydantic should know this type fully
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataImageDTO,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_overview import (
    ContentCounterDTO,
    PostCountDTO,
    PostTagDTO,
)
from boosty_downloader.infrastructure.boosty_api.models.post.subscription_level import (
    SubscriptionLevelDTO,
    TolerantCurrencyPrices,
)

# Overview data: a malformed value becomes None instead of failing the post.
TolerantTime = Annotated[datetime | None, WrapValidator(none_on_error)]
TolerantTags = Annotated[list[PostTagDTO] | None, WrapValidator(none_on_error)]
# The pictures shown in place of a post the account cannot open.
TolerantTeaser = Annotated[
    list[BoostyPostDataImageDTO] | None, WrapValidator(none_on_error)
]
TolerantContentCounters = Annotated[
    list[ContentCounterDTO] | None, WrapValidator(none_on_error)
]
TolerantPostCount = Annotated[PostCountDTO | None, WrapValidator(none_on_error)]


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

    publish_time: TolerantTime = None
    tags: TolerantTags = None
    teaser: TolerantTeaser = None
    content_counters: TolerantContentCounters = None
    count: TolerantPostCount = None

    data: list[BasePostData]
