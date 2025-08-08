"""Manager for downloading external videos (e.g., YouTube, Vimeo) with progress reporting."""
# ruff: noqa: I001

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, cast

from yt_dlp.YoutubeDL import YoutubeDL
from yt_dlp.utils import DownloadError

YOUTUBE_REGEX = r'^(?:https?://)?(?:www\.)?youtube\.com/(?:watch\?v=)?([^&\s]+)'
VIMEO_REGEX = r'^(?:https?://)?(?:www\.)?vimeo\.com/(\d+)'

YtDlOptions = dict[str, object]
ExternalVideoDownloadProgressHook = Callable[['ExternalVideoDownloadStatus'], None]


class ExternalVideoDownloadError(Exception):
    """Base class for external video download errors."""


class VideoInfoExtractionError(ExternalVideoDownloadError):
    """Raised when video information (e.g., title) cannot be extracted."""


class VideoDownloadError(ExternalVideoDownloadError):
    """Raised when the video download fails."""


class VideoDownloadInterruptedByUserError(VideoDownloadError):
    """Raised when the user interrupts the download (Ctrl+C)."""


@dataclass(slots=True)
class ExternalVideoDownloadStatus:
    """Status payload for reporting external video download progress."""

    name: str
    total_bytes: int | None
    downloaded_bytes: int | None
    speed: float | None
    percentage: float
    delta_bytes: int


@dataclass(slots=True)
class _HookState:
    last_downloaded: int = 0
    final_filename: Path | None = None


class ExternalVideosDownloader:
    """Manager for downloading external videos (YouTube, Vimeo) with a 720p preference."""

    # Prefer 720p when available, otherwise choose the best <=720, and finally any best.
    _default_ydl_options: ClassVar[YtDlOptions] = {
        'format': 'bv*[height=720]+ba/bv*[height>720]+ba/bv*+ba/b',
        'quiet': True,
        'no_warnings': True,
        'no_color': True,
        'noprogress': True,
    }

    def is_supported_video(self, url: str) -> bool:
        return bool(re.match(YOUTUBE_REGEX, url) or re.match(VIMEO_REGEX, url))

    def download_video(
        self,
        url: str,
        destination_directory: Path,
        progress_hook: ExternalVideoDownloadProgressHook | None = None,
    ) -> Path:
        info = self._probe_video(url)
        title = info.get('title')
        if not isinstance(title, str) or not title.strip():
            raise VideoInfoExtractionError

        clean_title = self._sanitize_title(title)
        destination_directory.mkdir(parents=True, exist_ok=True)

        outtmpl = self._build_outtmpl(destination_directory, clean_title)

        state = _HookState()
        internal_hook = self._make_progress_hook(outtmpl, progress_hook, state)

        options: YtDlOptions = self._default_ydl_options.copy()
        options['outtmpl'] = outtmpl
        options['progress_hooks'] = [internal_hook]

        try:
            with YoutubeDL(params=options) as ydl:
                try:
                    # yt-dlp isn't typed; cast to Any and coerce to int
                    errors: int = int(cast('Any', ydl).download([url]))
                except KeyboardInterrupt as e:  # pragma: no cover - user interrupt path
                    raise VideoDownloadInterruptedByUserError from e

            if errors != 0:
                raise VideoDownloadError

        except DownloadError as e:
            raise ExternalVideoDownloadError from e

        if state.final_filename is not None:
            return state.final_filename

        ext = info.get('ext')
        guessed_ext = ext if isinstance(ext, str) and ext else 'mp4'
        return destination_directory / f'{clean_title}.{guessed_ext}'

    def _probe_video(self, url: str) -> dict[str, Any]:
        # Extract metadata without downloading to validate and fetch title/ext.
        try:
            with YoutubeDL(
                {'quiet': True, 'no_warnings': True, 'skip_download': True}
            ) as ydl:
                raw = cast('Any', ydl).extract_info(url, download=False)
        except DownloadError as e:
            raise VideoInfoExtractionError from e

        if not isinstance(raw, dict):
            raise VideoInfoExtractionError
        return cast('dict[str, Any]', raw)

    @staticmethod
    def _sanitize_title(text: str) -> str:
        # Cross-platform safe subset.
        return ''.join(ch for ch in text if ch.isalnum() or ch == ' ')

    @staticmethod
    def _build_outtmpl(destination_directory: Path, title: str) -> str:
        return str(destination_directory / f'{title}.%(ext)s')

    def _make_progress_hook(
        self,
        outtmpl: str,
        user_hook: ExternalVideoDownloadProgressHook | None,
        state: _HookState,
    ) -> Callable[[dict[str, Any]], None]:
        def _hook(d: dict[str, Any]) -> None:
            filename = d.get('filename') or d.get('tmpfilename') or outtmpl
            name = Path(str(filename)).name

            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            downloaded = d.get('downloaded_bytes')
            speed = d.get('speed')

            total_i = int(total) if isinstance(total, (int, float)) else None
            downloaded_i = (
                int(downloaded) if isinstance(downloaded, (int, float)) else None
            )
            speed_f = float(speed) if isinstance(speed, (int, float)) else None

            if total_i and downloaded_i is not None and total_i > 0:
                percentage = (downloaded_i / total_i) * 100.0
            else:
                percentage = 0.0

            if downloaded_i is not None:
                delta = downloaded_i - state.last_downloaded
                state.last_downloaded = downloaded_i
            else:
                delta = 0

            status_payload = ExternalVideoDownloadStatus(
                name=name,
                total_bytes=total_i,
                downloaded_bytes=downloaded_i,
                speed=speed_f,
                percentage=percentage,
                delta_bytes=delta,
            )

            if user_hook is not None:
                with contextlib.suppress(Exception):
                    user_hook(status_payload)

            if d.get('status') in {'finished', 'postprocessing'}:
                f = d.get('filename')
                if isinstance(f, str):
                    state.final_filename = Path(f)

        return _hook
