"""The module with list representation of posts data"""

from typing import Literal

from pydantic import BaseModel


class PostDataListDataItem(BaseModel):
    """Represents a single data item in a list of post data chunks."""

    type: str
    modificator: str | None = ''
    content: str


class PostDataListItem(BaseModel):
    """Represents a single item in a list of post data chunks."""

    items: list['PostDataListItem'] = []
    data: list[PostDataListDataItem] = []


PostDataListItem.model_rebuild()


class PostDataList(BaseModel):
    """Represents a list of post data chunks."""

    type: Literal['list']
    items: list[PostDataListItem]
    style: str | None = None
