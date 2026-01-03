"""The module with file representation of audio data"""

from typing import Literal

from pydantic import BaseModel


class BoostyPostDataAudioDTO(BaseModel):
    """Audio content piece in posts"""

    type: Literal['audio_file']
    url: str
    title: str
