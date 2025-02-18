"""Main module which handles the download process"""

from __future__ import annotations

import http
import json
import mimetypes
from typing import TYPE_CHECKING

import aiofiles
from yarl import URL

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_file import (
    PostDataFile,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_image import (
    PostDataImage,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_link import (
    PostDataLink,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_text import (
    PostDataText,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_video import (
    PostDataVideo,
)
from boosty_downloader.src.download_manager.external_videos_downloader import (
    ExternalVideosDownloader,
    FailedToDownloadExternalVideoError,
)
from boosty_downloader.src.download_manager.utils.path_sanitizer import sanitize_string

if TYPE_CHECKING:
    from pathlib import Path

    import aiohttp

    from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
    from boosty_downloader.src.boosty_api.models.post.post import Post
    from boosty_downloader.src.loggers.base import Logger


class BoostyDownloadManager:
    """Main class which handles the download process"""

    def __init__(
        self,
        *,
        session: aiohttp.ClientSession,
        api_client: BoostyAPIClient,
        target_directory: Path,
        external_videos_downloader: ExternalVideosDownloader,
        logger: Logger,
    ) -> None:
        self.logger = logger
        self.session = session
        self._api_client = api_client
        self._target_directory = target_directory.absolute()
        self.external_videos_downloader = external_videos_downloader
        self.prepare_target_directory(self._target_directory)

    def prepare_target_directory(self, target_directory: Path) -> None:
        target_directory.mkdir(parents=True, exist_ok=True)

    async def download_textual_content(
        self,
        *,
        destination_directory: Path,
        textual_content: list[PostDataText | PostDataLink],
    ) -> None:
        post_text_file = destination_directory / 'post.txt'
        post_text_file.parent.mkdir(parents=True, exist_ok=True)
        self.logger.wait(f'Extracting post data: {len(textual_content)} chunks')

        # Merge all the text and link fragments into one file
        with post_text_file.open(mode='w+', encoding='utf-8') as f:
            for text_chunk in textual_content:
                try:
                    json_data: list[str] = json.loads(text_chunk.content)
                except json.JSONDecodeError:
                    continue

                if len(json_data) == 0:
                    continue

                clean_text = str(json_data[0])

                if isinstance(text_chunk, PostDataLink):
                    clean_text += f' [{text_chunk.url}]'

                f.write(clean_text + '\n')

    async def download_images(
        self,
        *,
        destination_directory: Path,
        images: list[PostDataImage],
    ) -> None:
        if len(images) == 0:
            return

        images_directory = destination_directory / 'images'
        images_directory.mkdir(parents=True, exist_ok=True)

        for image in images:
            url = URL(image.url).with_query(None)
            image_filename = images_directory / url.path.split('/')[-1]
            self.logger.wait(f'Downloading post image: {image.url}')

            async with self.session.get(url) as response:
                if response.status != http.HTTPStatus.OK:
                    continue

                content_type = response.headers.get('Content-Type')
                if content_type:
                    ext = mimetypes.guess_extension(content_type)
                    if ext is not None:
                        image_filename = image_filename.with_suffix(ext)

                with image_filename.open(mode='wb') as f:
                    f.write(await response.content.read())

    def _log_unsuccessful_video_download(
        self,
        destination_directory: Path,
        video_url: str,
    ) -> None:
        unsuccessful_log = destination_directory / 'unsuccessful_videos.txt'
        self.logger.warning(f'Video url will be logged to the {unsuccessful_log}')

        if video_url in (line.strip() for line in unsuccessful_log.open().readlines()):
            return

        with unsuccessful_log.open(mode='a', encoding='utf-8') as f:
            f.write(f'{video_url}\n')

    async def download_videos(
        self,
        destination_directory: Path,
        videos: list[PostDataVideo],
    ) -> None:
        if len(videos) == 0:
            return

        videos_directory = destination_directory / 'videos'
        videos_directory.mkdir(parents=True, exist_ok=True)

        for video in videos:
            if not self.external_videos_downloader.is_supported_video(video.url):
                self.logger.warning(f'Video url is not supported: {video.url}')
                self._log_unsuccessful_video_download(destination_directory, video.url)
                continue

            self.logger.info(f'Downloading external video: {video.url}')
            try:
                self.external_videos_downloader.download_video(
                    video.url,
                    videos_directory,
                )
            except FailedToDownloadExternalVideoError:
                self.logger.warning(f'Failed to download external video: {video.url}')
                self._log_unsuccessful_video_download(destination_directory, video.url)
                continue

    async def download_files(
        self,
        destination_directory: Path,
        files: list[PostDataFile],
        signed_query: str,
    ) -> None:
        if len(files) == 0:
            return

        files_directory = destination_directory / 'files'
        files_directory.mkdir(parents=True, exist_ok=True)

        for file in files:
            self.logger.info(f'Downloading file: {file.url}')

            access_url = f'{file.url}{signed_query}'

            async with self.session.get(access_url) as response:
                if response.status != http.HTTPStatus.OK:
                    self.logger.warning(f'Failed to download file: {file.url}')
                    self.logger.warning(
                        f'STATUS: {response.status}, ERROR: {response.reason}',
                    )
                    continue

                filename = files_directory / file.title
                async with aiofiles.open(filename, mode='wb') as f:
                    while chunk := await response.content.read(1024 * 1024):
                        await f.write(chunk)

    async def download_single_post(self, username: str, post: Post) -> None:
        author_directory = self._target_directory / username

        # If post has name the format is:
        # DATE - POST
        #
        # Otherwise:
        # DATE - No title (id_PART_OF_ID_FOR_UNIQUENESS)

        post_title = post.title
        if len(post.title) == 0:
            post_title = f'No title (id_{post.id[:8]})'

        post_name = f'{post.created_at.date()} - {sanitize_string(post_title).strip()}'

        post_directory = author_directory / post_name
        post_directory.mkdir(parents=True, exist_ok=True)

        # Link will be injected into texts
        textual_content: list[PostDataText | PostDataLink] = [
            data_chunk
            for data_chunk in post.data
            if isinstance(data_chunk, (PostDataText, PostDataLink))
        ]

        images: list[PostDataImage] = [
            data_chunk
            for data_chunk in post.data
            if isinstance(data_chunk, PostDataImage) and data_chunk.url
        ]

        videos: list[PostDataVideo] = [
            data_chunk
            for data_chunk in post.data
            if isinstance(data_chunk, PostDataVideo) and data_chunk.url
        ]

        files: list[PostDataFile] = [
            data_chunk
            for data_chunk in post.data
            if isinstance(data_chunk, PostDataFile) and data_chunk.url
        ]

        self.logger.info(f'Downloading post {post_name}')

        await self.download_files(
            destination_directory=author_directory / post_directory,
            files=files,
            signed_query=post.signed_query,
        )
        await self.download_textual_content(
            destination_directory=author_directory / post_directory,
            textual_content=textual_content,
        )
        await self.download_images(
            destination_directory=author_directory / post_directory,
            images=images,
        )
        await self.download_videos(
            destination_directory=author_directory / post_directory,
            videos=videos,
        )

    async def download_all_posts(self, username: str) -> None:
        async for response in self._api_client.iterate_over_posts(
            username,
            delay_seconds=1.5,
        ):
            posts = response.posts

            for post in posts:
                await self.download_single_post(username, post)
