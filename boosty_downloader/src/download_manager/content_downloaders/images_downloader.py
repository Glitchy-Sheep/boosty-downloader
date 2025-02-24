"""Module to download images from boosty post"""

from pathlib import Path
from typing import Callable

import aiohttp
from yarl import URL

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_image import (
    PostDataImage,
)
from boosty_downloader.src.download_manager.utils.base_file_downloader import (
    DownloadFileConfig,
    DownloadingStatus,
    download_file,
)


async def download_boosty_images(
    session: aiohttp.ClientSession,
    destination: Path,
    images: list[PostDataImage],
    on_status_update: Callable[[DownloadingStatus], None],
) -> None:
    """Download multiple videos from Boosty according to preffered quality"""
    if len(images) == 0:
        return

    destination.mkdir(parents=True, exist_ok=True)

    for image in images:
        filename = URL(image.url).name
        dl_config = DownloadFileConfig(
            session=session,
            url=image.url,
            filename=filename,
            destination=destination,
            on_status_update=on_status_update,
            guess_extension=True,
        )

        await download_file(dl_config=dl_config)
