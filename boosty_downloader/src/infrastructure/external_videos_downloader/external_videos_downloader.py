"""Manager for downloading external videos (e.g: YouTube, Vimeo)"""

import re
from pathlib import Path
from typing import ClassVar

from yt_dlp.utils import DownloadError
from yt_dlp.YoutubeDL import YoutubeDL

YOUTUBE_REGEX = r'^(?:https?:\/\/)?(?:www\.)?youtube\.com\/(?:watch\?v=)?([^&\s]+)'
VIMEO_REGEX = r'^(?:https?:\/\/)?(?:www\.)?vimeo\.com\/(\d+)'


class ExternalVideoDownloadError(Exception):
    """Base class for errors related to external video downloading."""


class VideoInfoExtractionError(ExternalVideoDownloadError):
    """Error raised when video information extraction fails (such as title)."""


class VideoDownloadError(ExternalVideoDownloadError):
    """Error raised when video download fails."""


class ExternalVideosDownloader:
    """Manager for downloading external videos (e.g: YouTube, Vimeo)"""

    _default_ydl_options: ClassVar[dict[str, str]] = {
        'format': 'bestvideo[height=720]+bestaudio/best[height=720]',
        'merge_output_format': 'mp4',
    }

    @staticmethod
    def _sanitize_title(text: str) -> str:
        return ''.join(ch for ch in text if ch.isalnum() or ch == ' ')

    def is_supported_video(self, url: str) -> bool:
        return bool(re.match(YOUTUBE_REGEX, url) or re.match(VIMEO_REGEX, url))

    def download_video(self, url: str, destination_directory: Path) -> Path:
        try:
            with YoutubeDL(params=self._default_ydl_options.copy()) as probe_ydl:
                info = probe_ydl.extract_info(url, download=False)  # type: ignore 3rd party typing absence
            if not info or 'ext' not in info or 'title' not in info:
                raise VideoInfoExtractionError

            clean_title = self._sanitize_title(info['title'])  # type: ignore 3rd party typing absence
            filename = f'{clean_title}.{info["ext"]}'
            output_path = destination_directory / filename

            options = self._default_ydl_options.copy()
            options['outtmpl'] = str(output_path)

            with YoutubeDL(params=options) as ydl:
                res: int = ydl.download([url])  # type: ignore 3rd party typing absence

            # Zero return code indicates success
            if res != 0:
                raise VideoDownloadError

        except DownloadError as e:
            raise ExternalVideoDownloadError from e
        else:
            return output_path
