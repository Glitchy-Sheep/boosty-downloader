"""Optional metadata used to describe a blog and its owner."""

from typing import Annotated

from pydantic import Field, WrapValidator

from boosty_downloader.infrastructure.boosty_api.models.base import (
    BoostyBaseDTO,
    none_on_error,
)
from boosty_downloader.infrastructure.boosty_api.models.post.base_post_data import (
    BasePostData,
)

TolerantString = Annotated[str | None, WrapValidator(none_on_error)]
TolerantPostCount = Annotated[
    Annotated[int, Field(strict=True, ge=0)] | None, WrapValidator(none_on_error)
]


class BlogOwnerDTO(BoostyBaseDTO):
    """Display metadata; the owner's name is not the blog slug."""

    avatar_url: TolerantString = None
    name: TolerantString = None


class BlogCountDTO(BoostyBaseDTO):
    """Counts on Boosty, independent of the locally downloaded library."""

    posts: TolerantPostCount = None


class BlogInfoDTO(BoostyBaseDTO):
    """Blog metadata with independently optional fields."""

    title: TolerantString = None
    description: Annotated[list[BasePostData] | None, WrapValidator(none_on_error)] = (
        None
    )
    cover_url: TolerantString = None
    owner: Annotated[BlogOwnerDTO | None, WrapValidator(none_on_error)] = None
    count: Annotated[BlogCountDTO | None, WrapValidator(none_on_error)] = None
