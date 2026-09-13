"""Dependencies and settings of one download run, shared by the download use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from boosty_downloader.application.run_statistics import RunStatistics

if TYPE_CHECKING:
    from aiohttp_retry import RetryClient

    from boosty_downloader.application.filtering import (
        BoostyOkVideoType,
        DownloadContentTypeFilter,
    )
    from boosty_downloader.application.ports import (
        FailureLog,
        PostCache,
        ProgressReporter,
    )
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )


@dataclass
class DownloadContext:
    """Aggregates dependencies and configuration for the download workflow."""

    author_name: str
    downloader_session: RetryClient
    external_videos_downloader: ExternalVideosDownloader
    post_cache: PostCache
    filters: list[DownloadContentTypeFilter]
    preferred_video_quality: BoostyOkVideoType
    progress_reporter: ProgressReporter
    failed_logger: FailureLog
    # Counters of this run, filled by the use cases and shown at the end.
    run_statistics: RunStatistics = field(default_factory=RunStatistics)
