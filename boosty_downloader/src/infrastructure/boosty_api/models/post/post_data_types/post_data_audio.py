"""Module with audio file representation of posts data"""

from typing import Literal

from boosty_downloader.src.infrastructure.boosty_api.models.base import BoostyBaseDTO


class BoostyPostDataAudioDTO(BoostyBaseDTO):
    """Audio content piece in posts"""

    type: Literal['audio_file']
    id: str
    url: str
    title: str
    size: int
    complete: bool
    time_code: int
    show_views_counter: bool
    upload_status: str | None
    views_counter: int
