"""The module provides tools to download videos from Boosty according to preffered quality."""

from pathlib import Path
from typing import Callable

import aiohttp

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_ok_video import (
    OkVideoType,
    PostDataOkVideo,
)
from boosty_downloader.src.download_manager.ok_video_ranking import get_best_video
from boosty_downloader.src.download_manager.utils.base_file_downloader import (
    DownloadFileConfig,
    DownloadingStatus,
    download_file,
)


class DownloadBoostyVideoError(Exception):
    """Raised when there is no available link for the video to download."""

    def __init__(self, video_title: str) -> None:
        super().__init__(f'No available link for the video {video_title}')


async def download_boosty_videos(
    session: aiohttp.ClientSession,
    destination: Path,
    preferred_quality: OkVideoType,
    boosty_videos: list[PostDataOkVideo],
    on_status_update: Callable[[DownloadingStatus], None],
) -> None:
    """Download multiple videos from Boosty according to preffered quality"""
    if len(boosty_videos) == 0:
        return

    destination.mkdir(parents=True, exist_ok=True)

    for video in boosty_videos:
        best_video = get_best_video(video.player_urls, preferred_quality)
        if best_video is None:
            raise DownloadBoostyVideoError(video.title)

        dl_config = DownloadFileConfig(
            session=session,
            url=best_video.url,
            filename=video.title,
            destination=destination,
            on_status_update=on_status_update,
            guess_extension=True,
        )

        await download_file(dl_config=dl_config)
