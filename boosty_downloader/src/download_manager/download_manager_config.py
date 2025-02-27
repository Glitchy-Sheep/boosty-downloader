"""All necessary dependency containers for the main class"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from aiohttp_retry import RetryClient

from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
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


@dataclass
class GeneralOptions:
    """Class that holds general options for the download manager (such as paths)"""

    target_directory: Path
    download_content_type_filter: list[DownloadContentTypeFilter]
