"""The module with list representation of posts data"""

from typing import Literal

from pydantic import BaseModel


class BoostyPostDataListDataItemDTO(BaseModel):
    """Represents a single data item in a list of post data chunks."""

    type: str
    modificator: str | None = ''
    content: str


class BoostyPostDataListItemDTO(BaseModel):
    """Represents a single item in a list of post data chunks."""

    items: list['BoostyPostDataListItemDTO'] = []
    data: list[BoostyPostDataListDataItemDTO] = []


BoostyPostDataListItemDTO.model_rebuild()


class BoostyPostDataListDTO(BaseModel):
    """Represents a list of post data chunks."""

    type: Literal['list']
    items: list[BoostyPostDataListItemDTO]
    style: Literal['ordered', 'unordered'] | None = None
