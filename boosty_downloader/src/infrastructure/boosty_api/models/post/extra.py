"""Models for meta info about posts or requests to boosty.to"""

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO


class Extra(BoostyBaseDTO):
    """Meta info for posts request, can be used for pagination mainly"""

    is_last: bool
    offset: str
