"""All necessary dependency containers for the main class"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from aiohttp_retry import RetryClient

from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_ok_video import (
    OkVideoType,
)
from boosty_downloader.src.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.src.loggers.base import Logger
from boosty_downloader.src.loggers.failed_downloads_logger import FailedDownloadsLogger


@dataclass
class LoggerDependencies:
    """Class that holds loggers for the download manager"""

    failed_downloads_logger: FailedDownloadsLogger
    logger: Logger


@dataclass
class NetworkDependencies:
    """Class that holds network dependencies for the download manager"""

    session: RetryClient
    api_client: BoostyAPIClient
    external_videos_downloader: ExternalVideosDownloader


class DownloadContentTypeFilter(Enum):
    """Class that holds content type filters for the download manager (such as videos, images, etc)"""

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

    def to_ok_video_type(self) -> OkVideoType:
        mapping = {
            VideoQualityOption.smallest_size: OkVideoType.lowest,
            VideoQualityOption.low: OkVideoType.low,
            VideoQualityOption.medium: OkVideoType.medium,
            VideoQualityOption.high: OkVideoType.high,
            VideoQualityOption.highest: OkVideoType.ultra_hd,
        }
        return mapping[self]


@dataclass
class GeneralOptions:
    """Class that holds general options for the download manager (such as paths)"""

    target_directory: Path
    download_content_type_filters: list[DownloadContentTypeFilter]
    request_delay_seconds: float
    preferred_video_quality: VideoQualityOption
