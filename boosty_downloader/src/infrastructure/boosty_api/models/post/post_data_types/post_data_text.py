"""The module with textual representation of posts data"""

from typing import Literal

from pydantic import BaseModel


class PostDataText(BaseModel):
    """Textual content piece in posts"""

    type: Literal['text']

    content: str
    modificator: str
