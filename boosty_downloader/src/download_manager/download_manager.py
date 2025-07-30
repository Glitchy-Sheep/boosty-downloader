"""Main module which handles the download process"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from rich.progress import Progress
from yarl import URL

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_file import (
    PostDataFile,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_header import (
    PostDataHeader,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_image import (
    PostDataImage,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_link import (
    PostDataLink,
)
from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_list import (
    PostDataList,
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
from boosty_downloader.src.boosty_api.utils.textual_post_extractor import (
    extract_textual_content,
)
from boosty_downloader.src.caching.post_cache import PostCache
from boosty_downloader.src.download_manager.download_manager_config import (
    DownloadContentTypeFilter,
)
from boosty_downloader.src.download_manager.utils.base_file_downloader import (
    DownloadFileConfig,
    download_file,
)
from boosty_downloader.src.download_manager.utils.human_readable_size import (
    human_readable_size,
)
from boosty_downloader.src.download_manager.utils.ok_video_ranking import get_best_video
from boosty_downloader.src.download_manager.utils.path_sanitizer import sanitize_string
from boosty_downloader.src.external_videos_downloader.external_videos_downloader import (
    FailedToDownloadExternalVideoError,
)
from boosty_downloader.src.html_reporter.html_reporter import HTMLReport, NormalText

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.src.boosty_api.models.post.post import Post
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
    files: list[PostDataFile] = field(default_factory=list[PostDataFile])

    # Video content
    ok_videos: list[PostDataOkVideo] = field(default_factory=list[PostDataOkVideo])
    videos: list[PostDataVideo] = field(default_factory=list[PostDataVideo])

    # For generating post document
    post_content: list[PostDataText | PostDataLink | PostDataImage] = field(
        default_factory=list[PostDataText | PostDataLink | PostDataImage],
    )


@dataclass
class PostLocation:
    """Configuration for downloading post location"""

    title: str
    username: str
    post_directory: Path

    @property
    def author_directory(self) -> Path:
        return self.post_directory.parent


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

        self._general_options = general_options
        self._network_dependencies = network_dependencies
        self._target_directory = general_options.target_directory.absolute()
        self._prepare_target_directory(self._target_directory)

        # Will track progress for multiple tasks (files, videos, etc)
        self.progress = Progress(
            transient=True,
            console=self.logger.console,
        )

    def _prepare_target_directory(self, target_directory: Path) -> None:
        target_directory.mkdir(parents=True, exist_ok=True)

    def _generate_post_location(self, username: str, post: Post) -> PostLocation:
        title = post.title or f'No title (id_{post.id[:8]})'
        author_directory = self._target_directory / username

        post_title = post.title
        if len(post.title) == 0:
            post_title = f'No title (id_{post.id[:8]})'

        post_title = sanitize_string(post_title).replace('.', '').strip()
        post_name = f'{post.created_at.date()} - {post_title}'
        post_directory = author_directory / post_name

        return PostLocation(
            title=title,
            username=username,
            post_directory=post_directory,
        )

    def _separate_post_content(self, post: Post) -> PostData:
        content_chunks = post.data

        post_data = PostData()

        for chunk in content_chunks:
            if isinstance(chunk, PostDataFile):
                post_data.files.append(chunk)
            elif isinstance(chunk, PostDataOkVideo):
                post_data.ok_videos.append(chunk)
            elif isinstance(chunk, PostDataVideo):
                post_data.videos.append(chunk)
            elif isinstance(chunk, PostDataHeader):
                pass  # TODO(#48): Implement header scraping mechanism  # noqa: FIX002 - will be fixed in a separate PR
            elif isinstance(chunk, PostDataList):
                pass  # TODO(#48): Implement list scraping mechanism  # noqa: FIX002 - will be fixed in a separate PR
            else:  # remaning Link, Text, Image blocks
                post_data.post_content.append(chunk)

        return post_data

    async def _save_post_content(
        self,
        destination: Path,
        post_content: list[PostDataText | PostDataLink | PostDataImage],
    ) -> None:
        if post_content:
            self.logger.info(
                f'Found {len(post_content)} post content chunks, saving...',
                tab_level=1,
            )
            destination.mkdir(parents=True, exist_ok=True)
        else:
            return

        post_file_path = destination / 'post_content.html'

        images_directory = destination / 'images'

        post = HTMLReport(filename=post_file_path)

        self.logger.wait(
            f'Generating post content at {post_file_path.parent / post_file_path.name}',
            tab_level=1,
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
                    session=self._network_dependencies.session,
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

    async def _download_files(
        self,
        destination: Path,
        post: Post,
        files: list[PostDataFile],
    ) -> None:
        if files:
            self.logger.info(
                f'Found {len(files)} files for the post, downloading...',
                tab_level=1,
            )
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
                session=self._network_dependencies.session,
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

    async def _download_boosty_videos(
        self,
        destination: Path,
        post: Post,
        boosty_videos: list[PostDataOkVideo],
        preferred_quality: OkVideoType,
    ) -> None:
        if boosty_videos:
            self.logger.info(
                f'Found {len(boosty_videos)} boosty videos for the post, downloading...',
                tab_level=1,
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
                session=self._network_dependencies.session,
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

    async def _download_external_videos(
        self,
        post: Post,
        destination: Path,
        videos: list[PostDataVideo],
    ) -> None:
        if videos:
            self.logger.info(
                f'Found {len(videos)} external videos for the post, downloading...',
                tab_level=1,
            )
            destination.mkdir(parents=True, exist_ok=True)
        else:
            return

        # Don't use progress indicator here because of sys.stderr / stdout collissionds
        # just let ytdl do the work and print the progress to the console by itself
        for idx, video in enumerate(videos):
            if not self._network_dependencies.external_videos_downloader.is_supported_video(
                video.url,
            ):
                continue

            try:
                self.logger.wait(
                    f'Start youtube-dl for ({idx}/{len(videos)}) video please wait: ({video.url})',
                    tab_level=1,
                )
                self._network_dependencies.external_videos_downloader.download_video(
                    video.url,
                    destination,
                )
            except FailedToDownloadExternalVideoError:
                await self.fail_downloads_logger.add_error(
                    f'Failed to download video {video.url} from post {post.title} which url is {BOOSTY_POST_BASE_URL / post.id}',
                )
                self.logger.error(  # noqa: TRY400 (log expected exception)
                    f'Failed to download video {video.url} it was added to the log {self.fail_downloads_logger.file_path}',
                    tab_level=1,
                )
                continue

    async def _download_single_post(
        self,
        username: str,
        post: Post,
    ) -> None:
        """
        Download a single post and all its content including:

            1. Files
            2. Boosty videos
            3. Images
            4. External videos (from YouTube and Vimeo)
        """
        post_data = self._separate_post_content(post)

        post_location_info = self._generate_post_location(username, post)

        if (
            DownloadContentTypeFilter.post_content
            in self._general_options.download_content_type_filters
        ):
            await self._save_post_content(
                destination=post_location_info.post_directory,
                post_content=post_data.post_content,
            )

        if (
            DownloadContentTypeFilter.files
            in self._general_options.download_content_type_filters
        ):
            await self._download_files(
                destination=post_location_info.post_directory / 'files',
                post=post,
                files=post_data.files,
            )

        if (
            DownloadContentTypeFilter.boosty_videos
            in self._general_options.download_content_type_filters
        ):
            await self._download_boosty_videos(
                destination=post_location_info.post_directory / 'boosty_videos',
                post=post,
                boosty_videos=post_data.ok_videos,
                preferred_quality=self._general_options.preferred_video_quality.to_ok_video_type(),
            )

        if (
            DownloadContentTypeFilter.external_videos
            in self._general_options.download_content_type_filters
        ):
            await self._download_external_videos(
                post=post,
                destination=post_location_info.post_directory / 'external_videos',
                videos=post_data.videos,
            )

    async def clean_cache(self, username: str) -> None:
        db_file = self._target_directory / username / PostCache.DEFAULT_CACHE_FILENAME
        if db_file.exists():
            self.logger.success(
                f'Removing posts cache: {db_file} for username {username}',
            )
            db_file.unlink()
        else:
            self.logger.info(
                f'Posts cache not found: {db_file} for username {username}',
            )

    async def only_check_total_posts(self, username: str) -> None:
        total = 0
        async for response in self._network_dependencies.api_client.iterate_over_posts(
            username,
            delay_seconds=self._general_options.request_delay_seconds,
            posts_per_page=100,
        ):
            total += len(response.posts)
            self.logger.wait(
                f'Collecting posts count... NEW({len(response.posts)}) TOTAL({total})',
            )

        self.logger.success(f'Total count of posts found: {total}')

    async def download_post_by_url(self, username: str, url: str) -> None:
        target_post_id = url.split('/')[-1].split('?')[0]

        self.logger.info(f'Extracted post id from url: {target_post_id}')

        async for response in self._network_dependencies.api_client.iterate_over_posts(
            username,
            delay_seconds=self._general_options.request_delay_seconds,
            posts_per_page=100,
        ):
            for post in response.posts:
                self.logger.info(
                    f'Searching for post by its id, please wait: {post.id}...',
                )
                if post.id == target_post_id:
                    self.logger.wait('FOUND post by id, downloading...')
                    await self._download_single_post(
                        username=username,
                        post=post,
                    )
                    self.logger.success('Post downloaded successfully!')
                    return

        self.logger.error('Post not found, please check the url and username.')
        self.logger.error(
            'If this happends even after correcting the url, please open an issue.',
        )

    async def download_all_posts(
        self,
        username: str,
    ) -> None:
        # Get all posts and its total count
        self.logger.wait(
            '[bold yellow]NOTICE[/bold yellow]: This may take a while, be patient',
        )
        self.logger.info(
            'Total count of posts is not known during downloading because of the API limitations.',
        )
        self.logger.info(
            'But you will notified about the progress during download.',
        )
        self.logger.info('-' * 80)
        self.logger.info(
            'Script will download:'
            f'{[elem.name for elem in self._general_options.download_content_type_filters]}',
        )
        self.logger.info('-' * 80)

        total_posts = 0
        current_post = 0

        self._post_cache = PostCache(self._target_directory / username)

        with self.progress:
            async for (
                response
            ) in self._network_dependencies.api_client.iterate_over_posts(
                username,
                delay_seconds=self._general_options.request_delay_seconds,
                posts_per_page=5,
            ):
                posts = response.posts
                total_posts += len(posts)

                self.logger.info(
                    f'Got new posts page: NEW({len(posts)}) TOTAL({total_posts})',
                )

                for post in posts:
                    current_post += 1
                    if not post.has_access:
                        self.logger.info(
                            f'Skipping post {post.title} because it is not accessible due to your subscription level',
                        )
                        continue

                    post_location_info = self._generate_post_location(
                        username=username,
                        post=post,
                    )

                    if self._post_cache.has_same_post(
                        title=post_location_info.title,
                        updated_at=post.updated_at,
                    ):
                        self.logger.info(
                            f'Skipping post {post_location_info.title} because it was already downloaded',
                        )
                        continue

                    self.logger.info(
                        f'Processing post ({current_post}/{total_posts}):  {post_location_info.title}',
                    )

                    await self._download_single_post(
                        username=username,
                        post=post,
                    )

                    self._post_cache.add_post_cache(
                        title=post_location_info.title,
                        updated_at=post.updated_at,
                    )

        self.logger.success('Finished downloading posts!')
