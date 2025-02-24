"""Main module which handles the download process"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel
from rich.progress import Progress

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
from boosty_downloader.src.download_manager.content_downloaders.boosty_video_downloader import (
    download_boosty_videos,
)
from boosty_downloader.src.download_manager.content_downloaders.external_video_downloader import (
    download_external_videos,
)
from boosty_downloader.src.download_manager.content_downloaders.files_downloader import (
    download_boosty_files,
)
from boosty_downloader.src.download_manager.content_downloaders.images_downloader import (
    download_boosty_images,
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

        post_data = self.separate_post_content(post)

        self.logger.info(f'Downloading post {post_name}')

        await download_boosty_files(
            session=self.session,
            destination=author_directory / post_directory / 'files',
            files=post_data.files,
            signed_query=post.signed_query,
            on_status_update=lambda status: self.logger.wait(
                str(status.downloaded_bytes),
            ),
        )

        await download_boosty_images(
            session=self.session,
            destination=author_directory / post_directory / 'images',
            images=post_data.images,
            on_status_update=lambda status: self.logger.wait(
                str(status.downloaded_bytes),
            ),
        )

        await download_boosty_videos(
            session=self.session,
            boosty_videos=post_data.ok_videos,
            destination=author_directory / post_directory / 'videos',
            preferred_quality=OkVideoType.medium,
            on_status_update=lambda status: self.logger.wait(
                str(status.downloaded_bytes),
            ),
        )

        await download_external_videos(
            destination=author_directory / post_directory,
            videos=post_data.videos,
            external_videos_downloader=self.external_videos_downloader,
        )

    async def download_all_posts(self, username: str) -> None:
        # Get all posts and its total count
        self.logger.wait(
            '[bold yellow]NOTICE[/bold yellow]: This may take a while, be patient',
        )
        self.logger.info(
            'Count of posts is not known during downloding because of the API limitations.',
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
