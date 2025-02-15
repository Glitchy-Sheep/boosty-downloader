"""Module with ok video representation of posts data"""

from datetime import timedelta
from enum import Enum

from boosty_api.models.post.base_post_data import BasePostData
from boosty_api.models.post.post_data_type import PostDataType
from pydantic import BaseModel


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


class PostDataOkVideo(BasePostData):
    """Ok video content piece in posts"""

    type = PostDataType.ok_video
    title: str
    failover_host: str
    duration: timedelta

    upload_status: str
    complete: bool
    player_urls: list[OkVideoUrl]
