"""Manager for downloading external videos (e.g: YouTube, Vimeo)"""

import re
from pathlib import Path

from yt_dlp.utils import DownloadError
from yt_dlp.YoutubeDL import YoutubeDL


class FailedToDownloadExternalVideoError(Exception):
    """Exception raised for errors in the input."""


class ExternalVideosDownloader:
    """Downloading manager for external videos (e.g: YouTube, Vimeo)."""

    def __init__(self) -> None:
        self.default_ydl_options = {
            'format': 'bestvideo[height=720]+bestaudio/best[height=720]',
            'merge_output_format': 'mp4',
        }

    def is_supported_video(self, url: str) -> bool:
        """Check if the given url is supported (video from youtube or vimeo)"""
        youtube_regex = (
            r'^(?:https?:\/\/)?(?:www\.)?youtube\.com\/(?:watch\?v=)?([^&\s]+)'
        )
        vimeo_regex = r'^(?:https?:\/\/)?(?:www\.)?vimeo\.com\/(\d+)'

        return bool(re.match(youtube_regex, url) or re.match(vimeo_regex, url))

    def download_video(self, url: str, destination_directory: Path) -> None:
        """Download video to the specified directory"""
        options = self.default_ydl_options.copy()
        options['outtmpl'] = str(destination_directory / '%(title)s.%(ext)s')

        with YoutubeDL(params=options) as ydl:
            try:
                res = ydl.download([url])  # type: ignore 3rd party library w/o annotations
                success_status_code = 0
                if res != success_status_code:
                    raise FailedToDownloadExternalVideoError
            except DownloadError as e:
                raise FailedToDownloadExternalVideoError from e
