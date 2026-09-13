"""
Media of one post on disk: images, files, audio, Boosty and external videos.

Owns the folder layout under the post directory and the filename policy of
every media kind. Whatever the transport, progress comes out as
MediaProgress and a failure as MediaDownloadError; cancellation propagates
as CancelledError with the partial file removed.
"""

from __future__ import annotations

import threading
from asyncio import CancelledError, get_running_loop, to_thread
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from yarl import URL

from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExtVideoError,
    ExtVideoInfoError,
    ExtVideoInterruptedByUserError,
)
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadError,
    DownloadFileConfig,
    download_file,
)
from boosty_downloader.infrastructure.path_sanitizer import (
    MAX_NAME_BYTES,
    sanitize_filename,
)

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
        self, message: str, resource_url: str, file: Path | None = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.resource_url = resource_url
        # Where the file would have been; already removed when set.
        self.file = file


# download_file appends a guessed extension to video names later:
# the byte budget here leaves room so that never re-truncates the name.
_GUESSED_EXTENSION_RESERVE_BYTES = 8

_EXT_VIDEO_INFO_FAILED = (
    "External video unavailable or access restricted (can't get info)"
)
_EXT_VIDEO_DOWNLOAD_FAILED = 'External video download failed'


def boosty_video_filename(video: PostDataChunkBoostyVideo) -> str:
    """Filename unique per video: titles repeat inside a post, ids never do."""
    title = video.title.strip() or 'video'
    return sanitize_filename(
        title,
        suffix=f' ({video.id[:8]})',
        max_bytes=MAX_NAME_BYTES - _GUESSED_EXTENSION_RESERVE_BYTES,
    )


def _remove_partial(file: Path | None) -> None:
    if file is not None:
        file.unlink(missing_ok=True)


class PostMediaDownloader:
    """Saves the media of one post under its directory, one subfolder per kind."""

    def __init__(
        self,
        http: RetryClient,
        external_videos: ExternalVideosDownloader,
        post_dir: Path,
    ) -> None:
        self._http = http
        self._external_videos = external_videos
        self._post_dir = post_dir

    async def download_image(
        self, image: PostDataChunkImage, on_progress: ProgressCallback
    ) -> Path:
        """Save an image. The name is a bare uuid: Content-Type gives the extension."""
        return await self._download(
            url=image.url,
            filename=URL(image.url).name,
            subdir='images',
            guess_extension=True,
            on_progress=on_progress,
        )

    async def download_file(
        self, file: PostDataChunkFile, on_progress: ProgressCallback
    ) -> Path:
        """Save an attachment under the author's filename, extension included."""
        return await self._download(
            url=file.url,
            filename=file.filename,
            subdir='files',
            guess_extension=False,
            on_progress=on_progress,
        )

    async def download_audio(
        self, audio: PostDataChunkAudio, on_progress: ProgressCallback
    ) -> Path:
        """Save an audio track under its title, which already carries the extension."""
        return await self._download(
            url=audio.url,
            filename=audio.title,
            subdir='audio',
            guess_extension=False,
            on_progress=on_progress,
        )

    async def download_boosty_video(
        self, video: PostDataChunkBoostyVideo, on_progress: ProgressCallback
    ) -> Path:
        """Save a Boosty video as 'Title (id8)' plus the extension Content-Type gives."""
        return await self._download(
            url=video.url,
            filename=boosty_video_filename(video),
            subdir='boosty_videos',
            guess_extension=True,
            on_progress=on_progress,
        )

    async def download_external_video(
        self, video: PostDataChunkExternalVideo, on_progress: ProgressCallback
    ) -> Path:
        """Save a YouTube/Vimeo video through yt-dlp, off the event loop."""
        destination = self._post_dir / 'external_videos'
        await to_thread(destination.mkdir, parents=True, exist_ok=True)

        loop = get_running_loop()
        cancel_requested = threading.Event()

        def relay(status: ExternalVideoDownloadStatus) -> None:
            # KeyboardInterrupt is yt-dlp's own abort path: raising it inside
            # the worker thread stops the download shortly after Ctrl+C.
            if cancel_requested.is_set():
                raise KeyboardInterrupt
            progress = MediaProgress(
                downloaded_bytes=status.downloaded_bytes or 0,
                total_bytes=status.total_bytes,
                delta_bytes=status.delta_bytes,
            )
            # yt-dlp calls the hook from its worker thread; the caller's
            # progress display must be touched only from the event loop.
            loop.call_soon_threadsafe(on_progress, progress)

        try:
            # yt-dlp is fully blocking: run it off the loop, or it freezes
            # every parallel download and the progress display.
            path = await to_thread(
                self._external_videos.download_video,
                url=video.url,
                destination_directory=destination,
                progress_hook=relay,
            )
        except CancelledError:
            cancel_requested.set()
            raise
        except ExtVideoInterruptedByUserError as e:
            raise CancelledError from e
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
        return path.relative_to(self._post_dir)

    async def _download(
        self,
        *,
        url: str,
        filename: str,
        subdir: str,
        guess_extension: bool,
        on_progress: ProgressCallback,
    ) -> Path:
        destination = self._post_dir / subdir
        await to_thread(destination.mkdir, parents=True, exist_ok=True)

        def relay(status: DownloadingStatus) -> None:
            on_progress(
                MediaProgress(
                    downloaded_bytes=status.total_downloaded_bytes,
                    total_bytes=status.total_bytes,
                    delta_bytes=status.downloaded_bytes,
                )
            )

        try:
            path = await download_file(
                DownloadFileConfig(
                    session=self._http,
                    url=url,
                    filename=filename,
                    destination=destination,
                    guess_extension=guess_extension,
                    on_status_update=relay,
                )
            )
        except DownloadCancelledError as e:
            _remove_partial(e.file)
            raise CancelledError from e
        except DownloadError as e:
            _remove_partial(e.file)
            raise MediaDownloadError(
                e.message, resource_url=e.resource_url, file=e.file
            ) from e
        return path.relative_to(self._post_dir)
