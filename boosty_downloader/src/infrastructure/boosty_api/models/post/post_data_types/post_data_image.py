"""The module with image representation of posts data"""

from typing import Literal

from pydantic import BaseModel


class PostDataImage(BaseModel):
    """Image content piece in posts"""

    type: Literal['image']
    url: str
    width: int
    height: int
