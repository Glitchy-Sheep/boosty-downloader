"""The module with list representation of posts data"""

from enum import Enum
from typing import Annotated, Literal

from pydantic import Field

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO
from boosty_downloader.src.infrastructure.boosty_api.models.unknown_value import (
    UnknownValue,
)


class BoostyListStyle(Enum):
    """List styles Boosty is known to send."""

    ordered = 'ordered'
    unordered = 'unordered'


class BoostyListItemType(Enum):
    """List sub-element types the list mapper understands."""

    text = 'text'


# Known sub-element types parse into the enum, anything new from Boosty is
# kept as BoostyUnknownValue instead of failing the whole page. left_to_right
# is required: the default smart mode lets the catch-all swallow known values.
TolerantListItemType = Annotated[
    BoostyListItemType | UnknownValue,
    Field(union_mode='left_to_right'),
]


# Known styles parse into the enum, a new style from Boosty is kept as
# BoostyUnknownValue instead of failing the whole page. left_to_right is
# required: the default smart mode lets the catch-all swallow known values.
TolerantListStyle = Annotated[
    # Order is validation priority, not cosmetics: None must precede the
    # catch-all UnknownValue, or a null style gets wrapped as unknown.
    BoostyListStyle | None | UnknownValue,  # noqa: RUF036
    Field(union_mode='left_to_right'),
]


class BoostyPostDataListDataItemDTO(BoostyBaseDTO):
    """Represents a single data item in a list of post data chunks."""

    type: TolerantListItemType
    modificator: str | None = ''
    content: str


class BoostyPostDataListItemDTO(BoostyBaseDTO):
    """Represents a single item in a list of post data chunks."""

    items: list['BoostyPostDataListItemDTO'] = Field(
        default_factory=list['BoostyPostDataListItemDTO']
    )
    data: list[BoostyPostDataListDataItemDTO] = Field(
        default_factory=list[BoostyPostDataListDataItemDTO]
    )


BoostyPostDataListItemDTO.model_rebuild()


class BoostyPostDataListDTO(BoostyBaseDTO):
    """Represents a list of post data chunks."""

    type: Literal['list']
    items: list[BoostyPostDataListItemDTO]
    style: TolerantListStyle = None
