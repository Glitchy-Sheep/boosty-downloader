"""Usual video links (on youtube and other services)"""

from typing import Literal

from pydantic import BaseModel


class PostDataVideo(BaseModel):
    """Video content piece in posts"""

    type: Literal['video']
    url: str
