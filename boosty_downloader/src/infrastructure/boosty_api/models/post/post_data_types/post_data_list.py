"""The module with list representation of posts data"""

from typing import Literal

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataListDataItemDTO(BoostyBaseDTO):
    """Represents a single data item in a list of post data chunks."""

    type: str
    modificator: str | None = ''
    content: str


class BoostyPostDataListItemDTO(BoostyBaseDTO):
    """Represents a single item in a list of post data chunks."""

    items: list['BoostyPostDataListItemDTO'] = []
    data: list[BoostyPostDataListDataItemDTO] = []


BoostyPostDataListItemDTO.model_rebuild()


class BoostyPostDataListDTO(BoostyBaseDTO):
    """Represents a list of post data chunks."""

    type: Literal['list']
    items: list[BoostyPostDataListItemDTO]
    style: Literal['ordered', 'unordered'] | None = None
