"""Usual video links (on youtube and other services)"""

from typing import Literal

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataExternalVideoDTO(BoostyBaseDTO):
    """Video content piece in posts"""

    type: Literal['video']
    url: str
