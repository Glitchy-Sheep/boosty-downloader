"""Main module which handles the download process"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from rich.progress import Progress
from yarl import URL

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_file import (
    PostDataFile,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_image import (
    PostDataImage,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_ok_video import (
    OkVideoType,
    PostDataOkVideo,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_video import (
    PostDataVideo,
)
from boosty_downloader.src.download_manager.external_videos_downloader import (
    FailedToDownloadExternalVideoError,
)
from boosty_downloader.src.download_manager.ok_video_ranking import get_best_video
from boosty_downloader.src.download_manager.utils.base_file_downloader import (
    DownloadFileConfig,
    download_file,
)
from boosty_downloader.src.download_manager.utils.path_sanitizer import sanitize_string

if TYPE_CHECKING:
    from pathlib import Path

    import aiohttp

    from boosty_downloader.src.boosty_api.core.client import BoostyAPIClient
    from boosty_downloader.src.boosty_api.models.post.post import Post
    from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_link import (
        PostDataLink,
    )
    from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_text import (
        PostDataText,
    )
    from boosty_downloader.src.download_manager.external_videos_downloader import (
        ExternalVideosDownloader,
    )
    from boosty_downloader.src.loggers.base import Logger


class PostData(BaseModel):
    """
    Group content chunk by their type

    We need this class for content separation from continious post data list.
    """

    # Other media
    files: list[PostDataFile] = []
    images: list[PostDataImage] = []

    # Video content
    ok_videos: list[PostDataOkVideo] = []
    videos: list[PostDataVideo] = []

    # Textual content
    textuals: list[PostDataText | PostDataLink] = []


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

        self.progress = Progress()

    def prepare_target_directory(self, target_directory: Path) -> None:
        target_directory.mkdir(parents=True, exist_ok=True)

    def separate_post_content(self, post: Post) -> PostData:
        content_chunks = post.data

        post_data = PostData()

        for chunk in content_chunks:
            if isinstance(chunk, PostDataFile):
                post_data.files.append(chunk)
            elif isinstance(chunk, PostDataImage):
                post_data.images.append(chunk)
            elif isinstance(chunk, PostDataOkVideo):
                post_data.ok_videos.append(chunk)
            elif isinstance(chunk, PostDataVideo):
                post_data.videos.append(chunk)
            else:  # remaning Link or Text block
                post_data.textuals.append(chunk)

        return post_data

    async def download_files(
        self,
        destination: Path,
        post: Post,
        files: list[PostDataFile],
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)

        for file in files:
            dl_config = DownloadFileConfig(
                session=self.session,
                url=file.url + post.signed_query,
                filename=file.title,
                destination=destination,
                on_status_update=lambda status: self.logger.wait(
                    str(status.downloaded_bytes),
                ),
                guess_extension=False,  # Extensions are already taken from the title
            )
            await download_file(dl_config=dl_config)

    async def download_boosty_videos(
        self,
        destination: Path,
        boosty_videos: list[PostDataOkVideo],
        preferred_quality: OkVideoType,
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)

        for video in boosty_videos:
            best_video = get_best_video(video.player_urls, preferred_quality)
            if best_video is None:
                return  # TODO: Handle no video case (logging?)

            dl_config = DownloadFileConfig(
                session=self.session,
                url=best_video.url,
                filename=video.title,
                destination=destination,
                on_status_update=lambda status: self.logger.wait(
                    str(status.downloaded_bytes),
                ),
                guess_extension=True,
            )

            await download_file(dl_config=dl_config)

    async def download_images(
        self,
        destination: Path,
        images: list[PostDataImage],
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)

        for image in images:
            filename = URL(image.url).name
            dl_config = DownloadFileConfig(
                session=self.session,
                url=image.url,
                filename=filename,
                destination=destination,
                on_status_update=lambda status: self.logger.wait(
                    str(status.downloaded_bytes),
                ),
                guess_extension=True,
            )
            await download_file(dl_config=dl_config)

    async def download_videos(
        self,
        destination: Path,
        ok_videos: list[PostDataOkVideo],
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)

        for video in ok_videos:
            best_video = get_best_video(video.player_urls, OkVideoType.medium)
            if best_video is None:
                # TODO: Handle no video case (logging?)
                return

            dl_config = DownloadFileConfig(
                session=self.session,
                url=best_video.url,
                filename=video.title,
                destination=destination,
                on_status_update=lambda status: self.logger.wait(
                    str(status.downloaded_bytes),
                ),
                guess_extension=True,
            )

            await download_file(dl_config=dl_config)

    async def download_external_videos(
        self,
        destination: Path,
        videos: list[PostDataVideo],
    ) -> None:
        destination.mkdir(parents=True, exist_ok=True)

        for video in videos:
            if not self.external_videos_downloader.is_supported_video(video.url):
                continue

            try:
                self.external_videos_downloader.download_video(
                    video.url,
                    destination,
                )
            except FailedToDownloadExternalVideoError:
                continue

    async def download_single_post(self, username: str, post: Post) -> None:
        """
        Download a single post and all its content including:

            1. Files
            2. Boosty videos
            3. Images
            4. External videos (from YouTube and Vimeo)
        """
        author_directory = self._target_directory / username

        post_title = post.title
        if len(post.title) == 0:
            post_title = f'No title (id_{post.id[:8]})'

        post_name = f'{post.created_at.date()} - {sanitize_string(post_title).strip()}'
        post_directory = author_directory / post_name
        post_directory.mkdir(parents=True, exist_ok=True)
        post_data = self.separate_post_content(post)

        await self.download_files(
            destination=author_directory / post_directory / 'files',
            post=post,
            files=post_data.files,
        )

        await self.download_videos(
            destination=author_directory / post_directory / 'videos',
            ok_videos=post_data.ok_videos,
        )

        await self.download_images(
            destination=author_directory / post_directory / 'images',
            images=post_data.images,
        )

        await self.download_external_videos(
            destination=author_directory / post_directory / 'external_videos',
            videos=post_data.videos,
        )

        # TODO: Extract post textuals (links and texts) to a separate file
        # we should do this in some convenient manner for the end user

    async def download_all_posts(self, username: str) -> None:
        # Get all posts and its total count
        self.logger.wait(
            '[bold yellow]NOTICE[/bold yellow]: This may take a while, be patient',
        )
        self.logger.info(
            'Total count of posts is not known during downloding because of the API limitations.',
        )
        self.logger.info(
            'But you will notified about the progress during download.',
        )

        total_posts = 0
        current_post = 0

        async for response in self._api_client.iterate_over_posts(
            username,
            delay_seconds=1,
        ):
            posts = response.posts
            total_posts += len(posts)

            self.logger.info(
                f'Got new posts page: NEW({len(posts)}) TOTAL({total_posts})',
            )

            for post in posts:
                current_post += 1
                title = post.title or f'No title (id_{post.id[:8]})'
                self.logger.info(
                    f'Downloading post ({current_post}/{total_posts}):  {title}',
                )
                await self.download_single_post(post=post, username=username)
