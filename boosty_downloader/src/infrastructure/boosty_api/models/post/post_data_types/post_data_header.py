"""Header of the posts"""

from typing import Literal

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataHeaderDTO(BoostyBaseDTO):
    """Header content piece in posts"""

    type: Literal['header']
    content: str
    modificator: str
