"""Main module which handles the download process"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.progress import Progress
from yarl import URL

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_file import (
    PostDataFile,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_link import (
    PostDataLink,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_ok_video import (
    OkVideoType,
    PostDataOkVideo,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_text import (
    PostDataText,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_video import (
    PostDataVideo,
)
from boosty_downloader.src.download_manager.html_reporter import (
    HTMLReport,
    NormalText,
)
from boosty_downloader.src.download_manager.ok_video_ranking import get_best_video
from boosty_downloader.src.download_manager.post_cache import PostCache
from boosty_downloader.src.download_manager.textual_post_extractor import (
    extract_textual_content,
)
from boosty_downloader.src.download_manager.utils.base_file_downloader import (
    DownloadFileConfig,
    download_file,
)
from boosty_downloader.src.download_manager.utils.human_readable_size import (
    human_readable_size,
)
from boosty_downloader.src.download_manager.utils.path_sanitizer import sanitize_string
from boosty_downloader.src.external_videos_downloader.external_videos_downloader import (
    FailedToDownloadExternalVideoError,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.src.boosty_api.models.post.post import Post
    from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_image import (
        PostDataImage,
    )
    from boosty_downloader.src.download_manager.download_manager_config import (
        GeneralOptions,
        LoggerDependencies,
        NetworkDependencies,
    )

BOOSTY_POST_BASE_URL = URL('https://boosty.to/post')


@dataclass
class PostData:
    """
    Group content chunk by their type

    We need this class for content separation from continious post data list.
    """

    # Other media
    files: list[PostDataFile] = field(default_factory=list)

    # Video content
    ok_videos: list[PostDataOkVideo] = field(default_factory=list)
    videos: list[PostDataVideo] = field(default_factory=list)

    # For generating post document
    post_content: list[PostDataText | PostDataLink | PostDataImage] = field(
        default_factory=list,
    )


class BoostyDownloadManager:
    """Main class which handles the download process"""

    def __init__(
        self,
        *,
        general_options: GeneralOptions,
        logger_dependencies: LoggerDependencies,
        network_dependencies: NetworkDependencies,
    ) -> None:
        self.logger = logger_dependencies.logger
        self.fail_downloads_logger = logger_dependencies.failed_downloads_logger

        self.session = network_dependencies.session
        self._api_client = network_dependencies.api_client
        self._target_directory = general_options.target_directory.absolute()
        self.external_videos_downloader = (
            network_dependencies.external_videos_downloader
        )
        self.prepare_target_directory(self._target_directory)

        # Will track progress for multiple tasks (files, videos, etc)
        self.progress = Progress(
            transient=True,
            console=self.logger.console,
        )

    def prepare_target_directory(self, target_directory: Path) -> None:
        target_directory.mkdir(parents=True, exist_ok=True)

    def separate_post_content(self, post: Post) -> PostData:
        content_chunks = post.data

        post_data = PostData()

        for chunk in content_chunks:
            if isinstance(chunk, PostDataFile):
                post_data.files.append(chunk)
            elif isinstance(chunk, PostDataOkVideo):
                post_data.ok_videos.append(chunk)
            elif isinstance(chunk, PostDataVideo):
                post_data.videos.append(chunk)
            else:  # remaning Link, Text, Image blocks
                post_data.post_content.append(chunk)

        return post_data

    async def save_post_content(
        self,
        destination: Path,
        post_content: list[PostDataText | PostDataLink | PostDataImage],
    ) -> None:
        if post_content:
            self.logger.info(
                f'Found {len(post_content)} post content chunks, saving...',
            )
            destination.mkdir(parents=True, exist_ok=True)
        else:
            return

        post_file_path = destination / 'post_content.html'

        images_directory = destination / 'images'

        post = HTMLReport(filename=post_file_path)

        self.logger.wait(
            f'Generating post content at {post_file_path.parent / post_file_path.name}',
        )

        for chunk in post_content:
            if isinstance(chunk, PostDataText):
                text = extract_textual_content(chunk.content)
                post.add_text(NormalText(text))
            elif isinstance(chunk, PostDataLink):
                text = extract_textual_content(chunk.content)
                post.add_link(NormalText(text), chunk.url)
                post.new_paragraph()
            else:  # Image
                images_directory.mkdir(parents=True, exist_ok=True)
                image = chunk

                filename = URL(image.url).name

                # Will be updated by downloader callback
                current_task = self.progress.add_task(
                    filename,
                    total=None,
                )

                dl_config = DownloadFileConfig(
                    session=self.session,
                    url=image.url,
                    filename=filename,
                    destination=images_directory,
                    on_status_update=lambda status,
                    task_id=current_task,
                    filename=filename: self.progress.update(
                        task_id=task_id,
                        total=status.total_bytes,
                        current=status.downloaded_bytes,
                        description=f'{filename} ({human_readable_size(status.downloaded_bytes or 0)}/{human_readable_size(status.total_bytes)})',
                    ),
                    guess_extension=True,
                )

                out_file = await download_file(dl_config=dl_config)
                if out_file.exists():
                    post.add_image('./images/' + out_file.name)
                self.progress.remove_task(current_task)

        post.save()

    async def download_files(
        self,
        destination: Path,
        post: Post,
        files: list[PostDataFile],
    ) -> None:
        if files:
            self.logger.info(f'Found {len(files)} files for the post, downloading...')
            destination.mkdir(parents=True, exist_ok=True)
        else:
            return

        total_task = self.progress.add_task(
            f'Downloading files (0/{len(files)})',
            total=len(files),
        )

        for idx, file in enumerate(files):
            # Will be updated by downloader callback
            current_task = self.progress.add_task(
                file.title,
                total=None,
            )

            dl_config = DownloadFileConfig(
                session=self.session,
                url=file.url + post.signed_query,
                filename=file.title,
                destination=destination,
                on_status_update=lambda status,
                task_id=current_task,
                filename=file.title: self.progress.update(
                    task_id=task_id,
                    completed=status.downloaded_bytes,
                    total=status.total_bytes,
                    description=f'{filename} ({human_readable_size(status.downloaded_bytes or 0)}/{human_readable_size(status.total_bytes)})',
                ),
                guess_extension=False,  # Extensions are already taken from the title
            )

            await download_file(dl_config=dl_config)
            self.progress.remove_task(current_task)
            self.progress.update(
                task_id=total_task,
                description=f'Downloading files ({idx + 1}/{len(files)})',
                advance=1,
            )
        self.progress.remove_task(total_task)

    async def download_boosty_videos(
        self,
        destination: Path,
        post: Post,
        boosty_videos: list[PostDataOkVideo],
        preferred_quality: OkVideoType,
    ) -> None:
        if boosty_videos:
            self.logger.info(
                f'Found {len(boosty_videos)} boosty videos for the post, downloading...',
            )
            destination.mkdir(parents=True, exist_ok=True)
        else:
            return

        total_task = self.progress.add_task(
            f'Downloading boosty videos (0/{len(boosty_videos)})',
            total=len(boosty_videos),
        )

        for idx, video in enumerate(boosty_videos):
            best_video = get_best_video(video.player_urls, preferred_quality)
            if best_video is None:
                await self.fail_downloads_logger.add_error(
                    f'Failed to find video for {video.title} from post {post.title} which url is {BOOSTY_POST_BASE_URL / post.id}',
                )
                continue

            # Will be updated by downloader callback
            current_task = self.progress.add_task(
                video.title,
                total=None,
            )

            dl_config = DownloadFileConfig(
                session=self.session,
                url=best_video.url,
                filename=video.title,
                destination=destination,
                on_status_update=lambda status,
                task_id=current_task,
                filename=video.title: self.progress.update(
                    task_id=task_id,
                    total=status.total_bytes,
                    current=status.downloaded_bytes,
                    description=f'{filename} ({human_readable_size(status.downloaded_bytes or 0)}/{human_readable_size(status.total_bytes)})',
                ),
                guess_extension=True,
            )

            await download_file(dl_config=dl_config)
            self.progress.remove_task(current_task)
            self.progress.update(
                task_id=total_task,
                description=f'Downloading boosty videos ({idx + 1}/{len(boosty_videos)})',
                advance=1,
            )
        self.progress.remove_task(total_task)

    async def download_external_videos(
        self,
        post: Post,
        destination: Path,
        videos: list[PostDataVideo],
    ) -> None:
        if videos:
            self.logger.info(
                f'Found {len(videos)} external videos for the post, downloading...',
            )
            destination.mkdir(parents=True, exist_ok=True)
        else:
            return

        # Don't use progress indicator here because of sys.stderr / stdout collissionds
        # just let ytdl do the work and print the progress to the console by itself
        for idx, video in enumerate(videos):
            if not self.external_videos_downloader.is_supported_video(video.url):
                continue

            try:
                self.logger.wait(
                    f'Start youtube-dl for ({idx}/{len(videos)}) video please wait: ({video.url})',
                )
                self.external_videos_downloader.download_video(
                    video.url,
                    destination,
                )
            except FailedToDownloadExternalVideoError:
                await self.fail_downloads_logger.add_error(
                    f'Failed to download video {video.url} from post {post.title} which url is {BOOSTY_POST_BASE_URL / post.id}',
                )
                continue

    async def download_single_post(
        self,
        post: Post,
        author_directory: Path,
        post_directory: Path,
    ) -> None:
        """
        Download a single post and all its content including:

            1. Files
            2. Boosty videos
            3. Images
            4. External videos (from YouTube and Vimeo)
        """
        post_data = self.separate_post_content(post)

        await self.save_post_content(
            destination=author_directory / post_directory,
            post_content=post_data.post_content,
        )

        await self.download_files(
            destination=author_directory / post_directory / 'files',
            post=post,
            files=post_data.files,
        )

        await self.download_boosty_videos(
            destination=author_directory / post_directory / 'boosty_videos',
            post=post,
            boosty_videos=post_data.ok_videos,
            preferred_quality=OkVideoType.medium,
        )

        await self.download_external_videos(
            post=post,
            destination=author_directory / post_directory / 'external_videos',
            videos=post_data.videos,
        )

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

        author_directory = self._target_directory / username
        author_directory.mkdir(parents=True, exist_ok=True)

        self._post_cache = PostCache(author_directory)

        with self.progress:
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
                    author_directory = self._target_directory / username

                    post_title = post.title
                    if len(post.title) == 0:
                        post_title = f'No title (id_{post.id[:8]})'

                    post_title = sanitize_string(post_title).replace('.', '').strip()
                    post_name = f'{post.created_at.date()} - {post_title}'
                    post_directory = author_directory / post_name
                    post_directory.mkdir(parents=True, exist_ok=True)

                    if self._post_cache.has_same_post(
                        title=post_name,
                        updated_at=post.updated_at,
                    ):
                        self.logger.info(
                            f'Skipping post {title} because it was already downloaded',
                        )
                        continue

                    self.logger.info(
                        f'Downloading post ({current_post}/{total_posts}):  {title}',
                    )

                    await self.download_single_post(
                        post=post,
                        author_directory=author_directory,
                        post_directory=post_directory,
                    )

                    self._post_cache.add_post_cache(
                        title=post_name,
                        updated_at=post.updated_at,
                    )
