"""Module to download files from boosty post using signed query"""

from pathlib import Path
from typing import Callable

import aiohttp

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_file import (
    PostDataFile,
)
from boosty_downloader.src.download_manager.utils.base_file_downloader import (
    DownloadFileConfig,
    DownloadingStatus,
    download_file,
)


async def download_boosty_files(
    session: aiohttp.ClientSession,
    destination: Path,
    files: list[PostDataFile],
    on_status_update: Callable[[DownloadingStatus], None],
    signed_query: str,
) -> None:
    """Download files from boosty post using signed query"""
    if len(files) == 0:
        return

    destination.mkdir(parents=True, exist_ok=True)

    for file in files:
        dl_config = DownloadFileConfig(
            session=session,
            url=file.url + signed_query,
            filename=file.title,
            destination=destination,
            on_status_update=on_status_update,
            guess_extension=False,  # Extensions are already taken from the title
        )

        await download_file(dl_config=dl_config)
