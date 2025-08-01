"""Header of the posts"""

from typing import Literal

from pydantic import BaseModel


class PostDataHeader(BaseModel):
    """Header content piece in posts"""

    type: Literal['header']
    content: str
