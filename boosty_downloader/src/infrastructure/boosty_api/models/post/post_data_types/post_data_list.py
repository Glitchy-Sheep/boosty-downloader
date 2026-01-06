"""The module with list representation of posts data"""

from typing import Literal

from pydantic import Field

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataListDataItemDTO(BoostyBaseDTO):
    """Represents a single data item in a list of post data chunks."""

    type: str
    modificator: str | None = ''
    content: str


class BoostyPostDataListItemDTO(BoostyBaseDTO):
    """Represents a single item in a list of post data chunks."""

    items: list['BoostyPostDataListItemDTO'] = Field(
        default_factory=lambda: list['BoostyPostDataListItemDTO']()
    )
    data: list[BoostyPostDataListDataItemDTO] = Field(
        default_factory=lambda: list[BoostyPostDataListDataItemDTO]()
    )


BoostyPostDataListItemDTO.model_rebuild()


class BoostyPostDataListDTO(BoostyBaseDTO):
    """Represents a list of post data chunks."""

    type: Literal['list']
    items: list[BoostyPostDataListItemDTO]
    style: Literal['ordered', 'unordered'] | None = None
