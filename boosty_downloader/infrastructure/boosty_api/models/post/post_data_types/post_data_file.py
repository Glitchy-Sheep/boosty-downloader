"""The module with file representation of posts data"""

from typing import Literal

from boosty_downloader.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataFileDTO(BoostyBaseDTO):
    """File content piece in posts"""

    type: Literal['file']
    url: str
    title: str
