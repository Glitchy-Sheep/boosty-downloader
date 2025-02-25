"""The module provides tools to download videos from YouTube and Vimeo as external sources of videos."""

from pathlib import Path

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_video import (
    PostDataVideo,
)
from boosty_downloader.src.download_manager.external_videos_downloader import (
    ExternalVideosDownloader,
    FailedToDownloadExternalVideoError,
)


async def download_external_videos(
    destination: Path,
    videos: list[PostDataVideo],
    external_videos_downloader: ExternalVideosDownloader,
) -> None:
    """Download multiple videos from Boosty according to preffered quality"""
    if len(videos) == 0:
        return

    destination.mkdir(parents=True, exist_ok=True)

    for video in videos:
        if not external_videos_downloader.is_supported_video(video.url):
            continue

        try:
            external_videos_downloader.download_video(
                video.url,
                destination,
            )
        except FailedToDownloadExternalVideoError:
            continue
