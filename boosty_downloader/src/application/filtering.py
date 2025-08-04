"""Content type filters for the download manager."""

from enum import Enum

from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)


class DownloadContentTypeFilter(Enum):
    """
    Class that holds content type filters for the download manager

    They can be used to download only specific parts of content.
    """

    boosty_videos = 'boosty_videos'
    external_videos = 'external_videos'
    post_content = 'post_content'
    files = 'files'


class VideoQualityOption(str, Enum):
    """Preferred video quality option for cli"""

    smallest_size = 'smallest_size'
    low = 'low'
    medium = 'medium'
    high = 'high'
    highest = 'highest'

    def to_ok_video_type(self) -> BoostyOkVideoType:
        mapping = {
            VideoQualityOption.smallest_size: BoostyOkVideoType.lowest,
            VideoQualityOption.low: BoostyOkVideoType.low,
            VideoQualityOption.medium: BoostyOkVideoType.medium,
            VideoQualityOption.high: BoostyOkVideoType.high,
            VideoQualityOption.highest: BoostyOkVideoType.ultra_hd,
        }
        return mapping[self]
