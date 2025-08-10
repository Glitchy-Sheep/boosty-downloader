"""The module with file representation of posts data"""

from typing import Literal

from pydantic import BaseModel


class BoostyPostDataFileDTO(BaseModel):
    """File content piece in posts"""

    type: Literal['file']
    url: str
    title: str
