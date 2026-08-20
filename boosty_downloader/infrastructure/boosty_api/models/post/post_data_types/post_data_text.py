"""The module with textual representation of posts data"""

from typing import Literal

from boosty_downloader.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataTextDTO(BoostyBaseDTO):
    """Textual content piece in posts"""

    type: Literal['text']

    content: str
    modificator: str
