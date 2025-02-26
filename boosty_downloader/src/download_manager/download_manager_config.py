"""All necessary dependency containers for the main class"""

from dataclasses import dataclass
from pathlib import Path

from aiohttp import ClientSession

from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.src.download_manager.external_videos_downloader import (
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

    session: ClientSession
    api_client: BoostyAPIClient
    external_videos_downloader: ExternalVideosDownloader


@dataclass
class GeneralOptions:
    """Class that holds general options for the download manager (such as paths)"""

    target_directory: Path
