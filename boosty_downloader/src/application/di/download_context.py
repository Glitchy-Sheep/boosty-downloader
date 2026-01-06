"""Define the DownloadContext dataclass and its dependencies for the download workflow."""

from dataclasses import dataclass

from aiohttp_retry import RetryClient

from boosty_downloader.src.application.filtering import (
    BoostyOkVideoType,
    DownloadContentTypeFilter,
)
from boosty_downloader.src.cli.console_progress_reporter import ProgressReporter
from boosty_downloader.src.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.src.infrastructure.loggers.failed_downloads_logger import (
    FailedDownloadsLogger,
)
from boosty_downloader.src.infrastructure.post_caching.post_cache import SQLitePostCache


@dataclass
class DownloadContext:
    """Aggregates dependencies and configuration for the download workflow."""

    author_name: str
    downloader_session: RetryClient
    external_videos_downloader: ExternalVideosDownloader
    post_cache: SQLitePostCache
    filters: list[DownloadContentTypeFilter]
    preferred_video_quality: BoostyOkVideoType
    progress_reporter: ProgressReporter
    failed_logger: FailedDownloadsLogger
