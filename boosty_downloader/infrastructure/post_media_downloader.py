"""
Adapt media names, progress and transport errors for the post executor.

The post owner persists destinations. Each transport owns temporary output and publishes only completed files.
"""

from __future__ import annotations

from asyncio import CancelledError
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yarl import URL

from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExtVideoError,
    ExtVideoInfoError,
    ExtVideoInterruptedByUserError,
    ExtVideoUnavailableError,
)
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadError,
    ReservedDownloadFileConfig,
    download_reserved_file,
)
from boosty_downloader.infrastructure.media_filenames import boosty_video_filename

if TYPE_CHECKING:
    from pathlib import Path

    from aiohttp_retry import RetryClient

    from boosty_downloader.domain.post_data_chunks import (
        PostDataChunkAudio,
        PostDataChunkBoostyVideo,
        PostDataChunkExternalVideo,
        PostDataChunkFile,
        PostDataChunkImage,
    )
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideoDownloadStatus,
        ExternalVideosDownloader,
    )
    from boosty_downloader.infrastructure.file_downloader import DownloadingStatus
    from boosty_downloader.infrastructure.media_publication import PublishedFile
    from boosty_downloader.infrastructure.media_transfer import ReserveMediaPath


@dataclass(frozen=True, slots=True)
class MediaProgress:
    """One step of a media download, the same shape for aiohttp and yt-dlp."""

    # Bytes received since the start of this file.
    downloaded_bytes: int
    total_bytes: int | None
    # Bytes received since the previous report.
    delta_bytes: int


ProgressCallback = Callable[[MediaProgress], None]


class MediaDownloadError(Exception):
    """A media piece could not be saved. The transport error is the cause."""

    def __init__(
        self,
        message: str,
        resource_url: str,
        file: Path | None = None,
        *,
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.resource_url = resource_url
        # Optional resource path for reporting; this error never owns cleanup.
        self.file = file
        # False when the piece is gone for good: another attempt cannot help.
        self.retryable = retryable


_EXT_VIDEO_INFO_FAILED = (
    "External video unavailable or access restricted (can't get info)"
)
_EXT_VIDEO_DOWNLOAD_FAILED = 'External video download failed'
_EXT_VIDEO_UNAVAILABLE = 'External video unavailable'


class PostMediaDownloader:
    """Download post media into destinations reserved by its record owner."""

    def __init__(
        self,
        http: RetryClient,
        external_videos: ExternalVideosDownloader,
    ) -> None:
        self._http = http
        self._external_videos = external_videos

    async def download_image(
        self,
        image: PostDataChunkImage,
        on_progress: ProgressCallback,
        *,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        """Save an image. The name is a bare uuid: Content-Type gives the extension."""
        return await self._download(
            url=image.url,
            filename=URL(image.url).name,
            reserve=reserve,
            guess_extension=True,
            on_progress=on_progress,
        )

    async def download_file(
        self,
        file: PostDataChunkFile,
        on_progress: ProgressCallback,
        *,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        """Save an attachment under the author's filename, extension included."""
        return await self._download(
            url=file.url,
            filename=file.filename,
            reserve=reserve,
            guess_extension=False,
            on_progress=on_progress,
        )

    async def download_audio(
        self,
        audio: PostDataChunkAudio,
        on_progress: ProgressCallback,
        *,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        """Save an audio track under its title, which already carries the extension."""
        return await self._download(
            url=audio.url,
            filename=audio.title,
            reserve=reserve,
            guess_extension=False,
            on_progress=on_progress,
        )

    async def download_boosty_video(
        self,
        video: PostDataChunkBoostyVideo,
        on_progress: ProgressCallback,
        *,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        """Save a Boosty video as 'Title (id8)' plus the extension Content-Type gives."""
        return await self._download(
            url=video.url,
            filename=boosty_video_filename(video.title, video.id),
            reserve=reserve,
            guess_extension=True,
            on_progress=on_progress,
        )

    async def download_external_video(
        self,
        video: PostDataChunkExternalVideo,
        on_progress: ProgressCallback,
        *,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        """Save a YouTube/Vimeo video through yt-dlp, off the event loop."""

        def relay(status: ExternalVideoDownloadStatus) -> None:
            on_progress(
                MediaProgress(
                    downloaded_bytes=status.downloaded_bytes or 0,
                    total_bytes=status.total_bytes,
                    delta_bytes=status.delta_bytes,
                )
            )

        try:
            return await self._external_videos.download_reserved_video(
                video.url, reserve, progress_hook=relay
            )
        except ExtVideoInterruptedByUserError as e:
            raise CancelledError from e
        except ExtVideoUnavailableError as e:
            # Deleted, private, blocked: the site's answer, not a passing failure.
            message = f'{_EXT_VIDEO_UNAVAILABLE}: {e.reason}'
            raise MediaDownloadError(
                message, resource_url=e.video_url or video.url, retryable=False
            ) from e
        except ExtVideoInfoError as e:
            raise MediaDownloadError(
                _EXT_VIDEO_INFO_FAILED, resource_url=video.url
            ) from e
        # The base class catches every present and future family member:
        # a raw yt-dlp failure must never escape as a traceback.
        except ExtVideoError as e:
            raise MediaDownloadError(
                _EXT_VIDEO_DOWNLOAD_FAILED, resource_url=e.video_url or video.url
            ) from e

    async def _download(
        self,
        *,
        url: str,
        filename: str,
        reserve: ReserveMediaPath,
        guess_extension: bool,
        on_progress: ProgressCallback,
    ) -> PublishedFile:
        def relay(status: DownloadingStatus) -> None:
            on_progress(
                MediaProgress(
                    downloaded_bytes=status.total_downloaded_bytes,
                    total_bytes=status.total_bytes,
                    delta_bytes=status.downloaded_bytes,
                )
            )

        try:
            return await download_reserved_file(
                ReservedDownloadFileConfig(
                    session=self._http,
                    url=url,
                    filename=filename,
                    reserve=reserve,
                    on_status_update=relay,
                    guess_extension=guess_extension,
                )
            )
        except DownloadCancelledError as error:
            raise CancelledError from error
        except DownloadError as error:
            raise MediaDownloadError(
                error.message, resource_url=error.resource_url
            ) from error
