"""The module with textual representation of posts data"""

from typing import Final, Literal

from boosty_downloader.infrastructure.boosty_api.models.base import BoostyBaseDTO

PARAGRAPH_END_MODIFIER: Final = 'BLOCK_END'


class BoostyPostDataTextDTO(BoostyBaseDTO):
    """Textual content piece in posts"""

    type: Literal['text']

    content: str
    modificator: str
