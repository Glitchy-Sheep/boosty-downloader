"""Main module which handles the download process"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

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
from boosty_downloader.src.html_reporter.html_reporter import (
    HTMLReport,
    NormalText,
    PostMetadata,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.src.boosty_api.core.oauth_client import OAuthBoostyAPIClient
    from boosty_downloader.src.boosty_api.models.post.post import Post
    from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_image import (
        PostDataImage,
    )
    from boosty_downloader.src.download_manager.download_manager_config import (
        GeneralOptions,
        LoggerDependencies,
        NetworkDependencies,
    )


@dataclass
class PostData:
    """
    Group content chunk by their type

    We need this class for content separation from continious post data list.
    """

    # Other media
    files: list[PostDataFile] = field(default_factory=list)  # type: ignore

    # Video content
    ok_videos: list[PostDataOkVideo] = field(default_factory=list)  # type: ignore
    videos: list[PostDataVideo] = field(default_factory=list)  # type: ignore

    # For generating post document
    post_content: list[PostDataText | PostDataLink | PostDataImage] = field(  # type: ignore
        default_factory=list,
    )


@dataclass
class PostLocation:
    """Configuration for downloading post location"""

    title: str  # Clean post title without date
    full_name: str  # Full name with date for folder/cache comparison
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

        # OAuth token refresh tracking to avoid excessive refresh attempts
        self._last_token_refresh_time: float | None = None
        self._token_refresh_cooldown_seconds = general_options.oauth_refresh_cooldown
        self._consecutive_failed_refresh_count = 0
        self._max_consecutive_refresh_attempts = (
            3  # Stop trying after 3 consecutive failures
        )

    def _prepare_target_directory(self, target_directory: Path) -> None:
        target_directory.mkdir(parents=True, exist_ok=True)

    def _generate_post_location(self, username: str, post: Post) -> PostLocation:
        author_directory = self._target_directory / username

        post_title = post.title
        if len(post.title) == 0:
            post_title = f'No title (id_{post.id[:8]})'

        post_title = sanitize_string(post_title).replace('.', '').strip()
        post_name = f'{post.created_at.date()} - {post_title}'
        post_directory = author_directory / post_name

        return PostLocation(
            title=post_title,  # Clean title for cache
            full_name=post_name,  # Full name with date for folder operations
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
            else:  # remaning Link, Text, Image blocks
                post_data.post_content.append(chunk)

        return post_data

    async def _save_post_content(
        self,
        destination: Path,
        post_content: list[PostDataText | PostDataLink | PostDataImage],
        post: Post,
        username: str,
        files: list[PostDataFile] | None = None,
        boosty_videos: list[PostDataOkVideo] | None = None,
        external_videos: list[PostDataVideo] | None = None,
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

        # Create post metadata for the HTML reporter
        post_metadata = PostMetadata(
            title=post.title or f'Пост без названия (ID: {post.id[:8]})',
            post_id=post.id,
            created_at=post.created_at,
            updated_at=post.updated_at,
            author=username,
            original_url=f'https://boosty.to/{username}/posts/{post.id}',
        )

        html_report = HTMLReport(filename=post_file_path, metadata=post_metadata)

        self.logger.wait(
            f'Generating post content at {post_file_path.parent / post_file_path.name}',
            tab_level=1,
        )

        for chunk in post_content:
            if isinstance(chunk, PostDataText):
                text = extract_textual_content(chunk.content)
                html_report.add_text(NormalText(text))
            elif isinstance(chunk, PostDataLink):
                text = extract_textual_content(chunk.content)
                html_report.add_link(NormalText(text), chunk.url)
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
                    html_report.add_image('./images/' + out_file.name)
                self.progress.remove_task(current_task)

        # Add files to HTML report
        if files:
            html_report.add_spacer()
            for file in files:
                local_path = (
                    f'./files/{file.title}'
                    if (destination / 'files' / file.title).exists()
                    else None
                )
                html_report.add_file(
                    filename=file.title,
                    title=file.title,
                    url=file.url,
                    size=None,  # File size is not available in the API
                    local_path=local_path,
                )

        # Add boosty videos to HTML report
        if boosty_videos:
            html_report.add_spacer()
            for video in boosty_videos:
                # Try to find the downloaded video file
                video_dir = destination / 'boosty_videos'
                local_path = None
                if video_dir.exists():
                    # Look for files starting with the video title
                    video_files = list(video_dir.glob(f'{video.title}*'))
                    if video_files:
                        local_path = f'./boosty_videos/{video_files[0].name}'

                # Format duration
                duration_str = None
                if video.duration:
                    total_seconds = int(video.duration.total_seconds())
                    minutes = total_seconds // 60
                    seconds = total_seconds % 60
                    duration_str = f'{minutes}:{seconds:02d}'

                html_report.add_video(
                    title=video.title,
                    url=video.player_urls[0].url if video.player_urls else '',
                    video_type='boosty',
                    duration=duration_str,
                    size=None,
                    local_path=local_path,
                )

        # Add external videos to HTML report
        if external_videos:
            html_report.add_spacer()
            for video in external_videos:
                # Try to find the downloaded video file
                video_dir = destination / 'external_videos'
                local_path = None
                if video_dir.exists():
                    # Look for video files (common extensions)
                    video_extensions = [
                        '*.mp4',
                        '*.mkv',
                        '*.avi',
                        '*.mov',
                        '*.wmv',
                        '*.webm',
                    ]
                    for ext in video_extensions:
                        video_files = list(video_dir.glob(ext))
                        if video_files:
                            local_path = f'./external_videos/{video_files[0].name}'
                            break

                html_report.add_video(
                    title=video.url,  # External videos don't have titles, use URL
                    url=video.url,
                    video_type='external',
                    duration=None,
                    size=None,
                    local_path=local_path,
                )

        html_report.save()

    async def _save_post_json(
        self,
        destination: Path,
        post: Post,
        raw_post_data: dict[str, Any] | None = None,
    ) -> None:
        """Save raw API response as JSON file for post"""
        destination.mkdir(parents=True, exist_ok=True)

        json_file_path = destination / 'post_api.json'

        self.logger.wait(
            f'Saving raw JSON data at {json_file_path.name}',
            tab_level=1,
        )

        import json

        # If raw_post_data is not provided, skip JSON saving
        if raw_post_data is None:
            self.logger.warning(
                'No raw API data available for JSON export, skipping...',
                tab_level=1,
            )
            return

        with json_file_path.open('w', encoding='utf-8') as file:
            json.dump(raw_post_data, file, ensure_ascii=False, indent=2)



    async def _save_post_txt(
        self,
        destination: Path,
        post: Post,
        username: str,
    ) -> None:
        """Save minimalistic text representation of post"""
        destination.mkdir(parents=True, exist_ok=True)

        txt_file_path = destination / 'post_info.txt'

        self.logger.wait(
            f'Saving text summary at {txt_file_path.name}',
            tab_level=1,
        )

        # Determine post type
        post_type = 'unknown'
        content_chunks = post.data

        # Analyze content to determine type
        has_text = any(chunk.type == 'text' for chunk in content_chunks)
        has_images = any(chunk.type == 'image' for chunk in content_chunks)
        has_videos = any(chunk.type in ['ok_video', 'video'] for chunk in content_chunks)
        has_files = any(chunk.type == 'file' for chunk in content_chunks)

        if has_text and not has_images and not has_videos and not has_files:
            post_type = 'text_only'
        elif has_images:
            post_type = 'with_images'
        elif has_videos:
            post_type = 'with_videos'
        elif has_files:
            post_type = 'with_files'
        elif has_text:
            post_type = 'text'

        # Extract text content
        from boosty_downloader.src.boosty_api.utils.textual_post_extractor import (
            extract_textual_content,
        )

        content_parts: list[str] = []
        for chunk in content_chunks:
            if chunk.type == 'text':
                text_content = extract_textual_content(chunk.content).strip()
                if text_content:
                    content_parts.append(text_content)
            elif chunk.type == 'link':
                link_text = extract_textual_content(chunk.content).strip()
                if link_text:
                    content_parts.append(link_text)
                content_parts.append(chunk.url)

        content_text = '\n'.join(content_parts)

        # Limit length for teaser
        teaser = content_text[:200] + '...' if len(content_text) > 200 else content_text
        if '\n' in teaser:
            teaser = teaser.split('\n')[0] + '...' if len(teaser.split('\n')[0]) < len(teaser) else teaser

        # Form file content
        txt_content = f"""Post
--------
ID: {post.id}
Type: {post_type}
Title: {post.title} 
Teaser: {teaser}

Content: {content_text}

Published: {post.created_at.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}+00:00
Last Edited: {post.updated_at.strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]}+00:00
URL: https://boosty.to/{username}/posts/{post.id}
"""

        with txt_file_path.open('w', encoding='utf-8') as file:
            file.write(txt_content)

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
        username: str,
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
                    f'Failed to find video for {video.title} from post {post.title} which url is https://boosty.to/{username}/posts/{post.id}',
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
        username: str,
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
                    f'Failed to download video {video.url} from post {post.title} which url is https://boosty.to/{username}/posts/{post.id}',
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
        raw_post_data: dict[str, Any] | None = None,
    ) -> bool:
        """
        Download a single post and all its content including:

            1. Files
            2. Boosty videos
            3. Images
            4. External videos (from YouTube and Vimeo)

        Returns:
            bool: True if the download was successful, False otherwise

        """
        try:
            post_data = self._separate_post_content(post)

            post_location_info = self._generate_post_location(username, post)

            # Check if post has any content to download
            has_content = (
                len(post_data.post_content) > 0
                or len(post_data.files) > 0
                or len(post_data.ok_videos) > 0
                or len(post_data.videos) > 0
            )

            if not has_content:
                self.logger.warning(
                    f'Post "{post.title}" has no downloadable content - it may be empty or inaccessible',
                    tab_level=1,
                )
                # Create a marker file to indicate this post was processed but empty
                post_location_info.post_directory.mkdir(parents=True, exist_ok=True)
                empty_marker_file = (
                    post_location_info.post_directory / 'EMPTY_POST_MARKER.txt'
                )
                empty_marker_file.write_text(
                    f'This post was processed but contained no downloadable content.\n'
                    f'Post ID: {post.id}\n'
                    f'Title: {post.title}\n'
                    f'Created: {post.created_at}\n'
                    f'Updated: {post.updated_at}\n'
                    f'Original URL: https://boosty.to/{username}/posts/{post.id}\n'
                    f'Processed at: {post_location_info.post_directory.name}\n'
                    f'\nThis may indicate:\n'
                    f'- The post was removed by the author\n'
                    f'- The post content is not accessible with your subscription level\n'
                    f'- The post contains only unsupported content types\n'
                    f'- The post is a text-only post with no media attachments\n',
                    encoding='utf-8',
                )
                self.logger.info(
                    f'Created empty post marker at {empty_marker_file}',
                    tab_level=1,
                )

                # Save JSON and TXT even for empty posts if options are enabled
                if self._general_options.save_raw_json:
                    await self._save_post_json(
                        destination=post_location_info.post_directory,
                        post=post,
                        raw_post_data=raw_post_data,
                    )

                if self._general_options.save_raw_txt:
                    await self._save_post_txt(
                        destination=post_location_info.post_directory,
                        post=post,
                        username=username,
                    )

                return True  # Still consider this a successful processing

            if (
                DownloadContentTypeFilter.post_content
                in self._general_options.download_content_type_filters
            ):
                await self._save_post_content(
                    destination=post_location_info.post_directory,
                    post_content=post_data.post_content,
                    post=post,
                    username=username,
                    files=post_data.files,
                    boosty_videos=post_data.ok_videos,
                    external_videos=post_data.videos,
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
                    username=username,
                )

            if (
                DownloadContentTypeFilter.external_videos
                in self._general_options.download_content_type_filters
            ):
                await self._download_external_videos(
                    post=post,
                    destination=post_location_info.post_directory / 'external_videos',
                    videos=post_data.videos,
                    username=username,
                )

            # Save raw JSON if option is enabled
            if self._general_options.save_raw_json:
                await self._save_post_json(
                    destination=post_location_info.post_directory,
                    post=post,
                    raw_post_data=raw_post_data,
                )

            # Save TXT if option is enabled
            if self._general_options.save_raw_txt:
                await self._save_post_txt(
                    destination=post_location_info.post_directory,
                    post=post,
                    username=username,
                )

        except Exception:
            self.logger.error(f'Failed to download post {post.title}')
            # Log the exception using the underlying logger
            self.logger.logging_logger_obj.exception(
                f'Exception details for failed post download: {post.title}',
            )
            return False
        else:
            return True

    async def _handle_inaccessible_post_with_retry(
        self,
        username: str,
        post: Post,
        post_location_info: PostLocation,
        stats: dict[str, int],
    ) -> bool:
        """
        Handle inaccessible post with OAuth token refresh retry.

        Returns True if the post should be skipped (still inaccessible),
        False if the post should be processed normally (access gained).
        """
        # Check if we have OAuth authentication
        api_client = self._network_dependencies.api_client
        if not hasattr(api_client, 'force_refresh_tokens'):
            # Not an OAuth client, skip immediately
            await self._log_inaccessible_post(post, post_location_info, username)
            stats['inaccessible'] += 1
            return True

        # Type assertion for OAuth client
        oauth_client: OAuthBoostyAPIClient = api_client  # type: ignore

        # Check if we should attempt token refresh based on cooldown and failure count
        current_time = time.time()
        should_attempt_refresh = True

        # Don't attempt if we've had too many consecutive failures
        if (
            self._consecutive_failed_refresh_count
            >= self._max_consecutive_refresh_attempts
        ):
            should_attempt_refresh = False
            self.logger.info(
                f'Skipping token refresh for "{post.title}" - too many consecutive failures '
                f'({self._consecutive_failed_refresh_count}/{self._max_consecutive_refresh_attempts})',
                tab_level=1,
            )

        # Don't attempt if we're still in cooldown period
        elif (
            self._last_token_refresh_time is not None
            and current_time - self._last_token_refresh_time
            < self._token_refresh_cooldown_seconds
        ):
            should_attempt_refresh = False
            remaining_cooldown = self._token_refresh_cooldown_seconds - (
                current_time - self._last_token_refresh_time
            )
            self.logger.info(
                f'Skipping token refresh for "{post.title}" - cooldown active '
                f'({remaining_cooldown:.0f}s remaining)',
                tab_level=1,
            )

        if not should_attempt_refresh:
            await self._log_inaccessible_post(post, post_location_info, username)
            stats['inaccessible'] += 1
            return True

        # Try to force refresh OAuth tokens
        self.logger.info(
            f'Post "{post.title}" is inaccessible, attempting to refresh OAuth tokens...',
            tab_level=1,
        )

        self._last_token_refresh_time = current_time
        token_refreshed: bool = await oauth_client.force_refresh_tokens()

        if not token_refreshed:
            self._consecutive_failed_refresh_count += 1
            self.logger.info(
                f'OAuth token refresh failed or not needed, skipping post "{post.title}" '
                f'(failure #{self._consecutive_failed_refresh_count})',
                tab_level=1,
            )
            await self._log_inaccessible_post(post, post_location_info, username)
            stats['inaccessible'] += 1
            return True

        # Reset consecutive failure count on successful refresh
        self._consecutive_failed_refresh_count = 0

        # Try to get the post again with refreshed tokens
        self.logger.info(
            f'OAuth tokens refreshed, retrying post "{post.title}"...',
            tab_level=1,
        )

        try:
            # Make a single post request to check if we now have access
            response = await oauth_client.get_author_posts(
                author_name=username,
                limit=1,
                offset=None,
            )

            # Try to find our post in the response
            for refreshed_post in response.posts:
                if refreshed_post.id == post.id:
                    if refreshed_post.has_access:
                        self.logger.success(
                            f'Access gained to post "{post.title}" after token refresh!',
                            tab_level=1,
                        )
                        # Update the post object with the refreshed version
                        post.has_access = True
                        post.data = refreshed_post.data
                        post.signed_query = refreshed_post.signed_query
                        return False  # Don't skip, process normally
                    self.logger.info(
                        f'Post "{post.title}" is still inaccessible after token refresh',
                        tab_level=1,
                    )
                    break

            # If we get here, the post is still inaccessible
            await self._log_inaccessible_post(post, post_location_info, username)
            stats['inaccessible'] += 1
            return True

        except Exception as e:
            self.logger.error(
                f'Error while retrying post "{post.title}" after token refresh: {e}',
                tab_level=1,
            )
            await self._log_inaccessible_post(post, post_location_info, username)
            stats['inaccessible'] += 1
            return True

    async def _log_inaccessible_post(
        self,
        post: Post,
        post_location_info: PostLocation,
        username: str,
    ) -> None:
        """Log information about inaccessible posts without creating files"""
        # Log detailed information about the inaccessible post
        self.logger.warning(
            f'Post "{post.title}" is not accessible with your current subscription level',
            tab_level=1,
        )
        self.logger.info(
            f'Post ID: {post.id}',
            tab_level=2,
        )
        self.logger.info(
            f'Created: {post.created_at}',
            tab_level=2,
        )
        self.logger.info(
            f'Updated: {post.updated_at}',
            tab_level=2,
        )
        self.logger.info(
            f'Original URL: https://boosty.to/{username}/posts/{post.id}',
            tab_level=2,
        )
        self.logger.info(
            'To access this post, you may need to:',
            tab_level=2,
        )
        self.logger.info(
            '- Subscribe to the author at a higher tier',
            tab_level=2,
        )
        self.logger.info(
            '- Purchase this specific post',
            tab_level=2,
        )
        self.logger.info(
            '- Check if your subscription is still active',
            tab_level=2,
        )
        self.logger.info(
            '- Verify that your OAuth tokens are valid',
            tab_level=2,
        )
        # DO NOT add inaccessible posts to cache - they might become accessible later
        # This allows retrying inaccessible posts on subsequent runs
        self.logger.info(
            f'Post "{post.title}" will be retried on next run in case access is granted',
            tab_level=2,
        )

    def reset_oauth_retry_state(self) -> None:
        """
        Reset OAuth token refresh cooldown and failure tracking.

        This can be useful for debugging or when you want to force
        immediate retry attempts regardless of previous failures.
        """
        self._last_token_refresh_time = None
        self._consecutive_failed_refresh_count = 0
        self.logger.info('OAuth retry state reset - cooldown and failure count cleared')

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

        # Initialize cache for this user
        post_cache = PostCache(self._target_directory / username)

        async for response in self._network_dependencies.api_client.iterate_over_posts(
            username,
            delay_seconds=self._general_options.request_delay_seconds,
            posts_per_page=100,
        ):
            # Get raw data for posts if available
            raw_posts_data = response.raw_posts_data if hasattr(response, 'raw_posts_data') else []

            for i, post in enumerate(response.posts):
                self.logger.info(
                    f'Searching for post by its id, please wait: {post.id}...',
                )
                if post.id == target_post_id:
                    # Get corresponding raw data for this post
                    raw_post_data = raw_posts_data[i] if i < len(raw_posts_data) else None

                    self.logger.wait('FOUND post by id, downloading...')
                    if await self._download_single_post(
                        username=username,
                        post=post,
                        raw_post_data=raw_post_data,
                    ):
                        post_location_info = self._generate_post_location(
                            username,
                            post,
                        )
                        post_cache.add_post_cache(
                            post_id=post.id,
                            title=post_location_info.title,
                            updated_at=post.updated_at,
                        )
                        self.logger.success('Post downloaded successfully!')
                    else:
                        self.logger.error('Failed to download post!')
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

        # Statistics tracking
        stats = {
            'downloaded': 0,
            'skipped_cached': 0,
            'inaccessible': 0,
            'empty': 0,
            'failed': 0,
        }

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

                # Get raw data for posts if available
                raw_posts_data = response.raw_posts_data if hasattr(response, 'raw_posts_data') else []

                for i, post in enumerate(posts):
                    current_post += 1

                    post_location_info = self._generate_post_location(
                        username=username,
                        post=post,
                    )

                    # Get corresponding raw data for this post
                    raw_post_data = raw_posts_data[i] if i < len(raw_posts_data) else None

                    if not post.has_access:
                        # Try to handle the inaccessible post with OAuth token refresh
                        should_skip = await self._handle_inaccessible_post_with_retry(
                            username=username,
                            post=post,
                            post_location_info=post_location_info,
                            stats=stats,
                        )
                        if should_skip:
                            continue
                        # If not skipping, the post access was gained, continue with normal processing

                    # Ensure folder name matches current post title (rename if needed)
                    self._post_cache.ensure_folder_name_matches(
                        post_id=post.id,
                        current_title=post_location_info.title,
                        created_at=post.created_at,
                    )

                    if self._post_cache.has_same_post(
                        post_id=post.id,
                        current_title=post_location_info.title,
                        updated_at=post.updated_at,
                        current_folder_name=post_location_info.full_name,
                    ):
                        self.logger.info(
                            f'Skipping post {post_location_info.full_name} because it was already downloaded',
                        )
                        stats['skipped_cached'] += 1
                        continue

                    self.logger.info(
                        f'Processing post ({current_post}/{total_posts}):  {post_location_info.full_name}',
                    )

                    download_result = await self._download_single_post(
                        username=username,
                        post=post,
                        raw_post_data=raw_post_data,
                    )

                    if download_result:
                        self._post_cache.add_post_cache(
                            post_id=post.id,
                            title=post_location_info.title,
                            updated_at=post.updated_at,
                        )

                        # Check if this was an empty post
                        empty_marker_file = (
                            post_location_info.post_directory / 'EMPTY_POST_MARKER.txt'
                        )
                        if empty_marker_file.exists():
                            stats['empty'] += 1
                        else:
                            stats['downloaded'] += 1
                    else:
                        self.logger.error(f'Failed to download post: {post.title}')
                        stats['failed'] += 1
                        # Still add to cache to avoid retrying failed posts repeatedly
                        self._post_cache.add_post_cache(
                            post_id=post.id,
                            title=post_location_info.title,
                            updated_at=post.updated_at,
                        )

        # Print final statistics
        self.logger.success('Finished downloading posts!')
        self.logger.info('-' * 80)
        self.logger.info('[bold cyan]DOWNLOAD STATISTICS[/bold cyan]')
        self.logger.info(f'📊 Total posts processed: {total_posts}')
        self.logger.info(f'✅ Successfully downloaded: {stats["downloaded"]}')
        self.logger.info(f'📁 Skipped (already cached): {stats["skipped_cached"]}')
        self.logger.info(f'🔒 Inaccessible posts: {stats["inaccessible"]}')
        self.logger.info(f'📄 Empty posts: {stats["empty"]}')
        self.logger.info(f'❌ Failed downloads: {stats["failed"]}')
        self.logger.info('-' * 80)

        # Log warnings if there are issues
        if stats['inaccessible'] > 0:
            self.logger.warning(
                f'Found {stats["inaccessible"]} inaccessible posts. '
                'Consider upgrading your subscription or checking authentication.',
            )

        if stats['empty'] > 0:
            self.logger.warning(
                f'Found {stats["empty"]} empty posts. '
                'These may have been removed by the author or contain unsupported content.',
            )

        if stats['failed'] > 0:
            self.logger.error(
                f'Failed to download {stats["failed"]} posts. '
                f'Check the failed downloads log at: {self.fail_downloads_logger.file_path}',
            )
