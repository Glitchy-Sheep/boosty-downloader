"""The module with file representation of posts data"""

from typing import Literal

from boosty_downloader.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataFileDTO(BoostyBaseDTO):
    """File content piece in posts"""

    type: Literal['file']
    url: str
    title: str
    size: int | None = None
    # False while the author's upload is still running: the url answers
    # 404 until it finishes. A missing flag means the file is there.
    complete: bool = True
