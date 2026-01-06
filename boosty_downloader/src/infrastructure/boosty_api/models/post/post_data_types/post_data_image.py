"""The module with image representation of posts data"""

from typing import Literal

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataImageDTO(BoostyBaseDTO):
    """Image content piece in posts"""

    type: Literal['image']
    url: str
    width: int | None = None
    height: int | None = None
