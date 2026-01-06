"""Module with link representation of posts data"""

from typing import Literal

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataLinkDTO(BoostyBaseDTO):
    """Link content piece in posts"""

    type: Literal['link']
    url: str
    content: str
    explicit: bool
