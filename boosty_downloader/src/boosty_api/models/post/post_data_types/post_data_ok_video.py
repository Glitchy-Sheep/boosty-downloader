"""Module with ok video representation of posts data"""

from __future__ import annotations

from datetime import timedelta  # noqa: TC003 Pydantic should know this type fully
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class OkVideoType(Enum):
    """All the types which boosty provides for ok video"""

    live_playback_dash = 'live_playback_dash'
    live_playback_hls = 'live_playback_hls'
    live_ondemand_hls = 'live_ondemand_hls'

    live_dash = 'live_dash'
    live_hls = 'live_hls'
    hls = 'hls'
    dash = 'dash'
    dash_uni = 'dash_uni'
    live_cmaf = 'live_cmaf'

    ultra_hd = 'ultra_hd'
    quad_hd = 'quad_hd'
    full_hd = 'full_hd'
    high = 'high'
    medium = 'medium'
    low = 'low'
    tiny = 'tiny'
    lowest = 'lowest'


class OkVideoUrl(BaseModel):
    """Link to video with specific format (link can be empty for some formats)"""

    url: str
    type: OkVideoType


class PostDataOkVideo(BaseModel):
    """Ok video content piece in posts"""

    type: Literal['ok_video']

    title: str
    failover_host: str
    duration: timedelta

    upload_status: str
    complete: bool
    player_urls: list[OkVideoUrl]

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )
