"""The module with image representation of posts data"""

from typing import Literal

from boosty_downloader.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataImageDTO(BoostyBaseDTO):
    """Image content piece in posts"""

    type: Literal['image']
    url: str
    size: int | None = None
    width: int | None = None
    height: int | None = None
