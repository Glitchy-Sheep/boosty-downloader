"""Module with link representation of posts data"""

from typing import Literal

from pydantic import BaseModel


class BoostyPostDataLinkDTO(BaseModel):
    """Link content piece in posts"""

    type: Literal['link']
    url: str
    content: str
    explicit: bool
