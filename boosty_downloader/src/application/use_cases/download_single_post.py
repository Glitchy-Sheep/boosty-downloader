"""
Use case for downloading a single post from Boosty.

It encapsulates the logic required to download a post from a specific author.
"""

import uuid
from asyncio import CancelledError
from pathlib import Path

from yarl import URL

from boosty_downloader.src.application.di.download_context import DownloadContext
from boosty_downloader.src.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.src.application.filtering import (
    DownloadContentTypeFilter,
)
from boosty_downloader.src.application.mappers import map_post_dto_to_domain
from boosty_downloader.src.application.mappers.html_converter import (
    PostDataChunkTextualList,
    convert_audio_to_html,
    convert_list_to_html,
    convert_text_to_html,
    convert_video_to_html,
)
from boosty_downloader.src.domain.post import (
    Post,
    PostDataAllChunks,
    PostDataChunkImage,
)
from boosty_downloader.src.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkText,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.src.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideoDownloadStatus,
    ExtVideoDownloadError,
    ExtVideoInfoError,
    ExtVideoInterruptedByUserError,
)
from boosty_downloader.src.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadError,
    DownloadFileConfig,
    DownloadingStatus,
    download_file,
)
from boosty_downloader.src.infrastructure.html_generator import (
    HtmlGenChunk,
    HtmlGenImage,
)
from boosty_downloader.src.infrastructure.html_generator.renderer import (
    render_html_to_file,
)
from boosty_downloader.src.infrastructure.human_readable_filesize import (
    human_readable_size,
)


def _form_post_url(username: str, post_id: str) -> str:
    return f'https://boosty.to/{username}/posts/{post_id}'


class DownloadSinglePostUseCase:
    """
    Use case for downloading all user's posts.

    This class encapsulates the logic required to download all posts from a source.
    Initialize the use case and call its methods to perform the download operation.

    All the downloaded content parts will be saved under the specified destination path.
    """

    def __init__(
        self,
        destination: Path,
        post_dto: PostDTO,
        download_context: DownloadContext,
    ) -> None:
        self.destination = destination
        self.post_dto = post_dto
        self.context = download_context

        self.post_file_path = destination / Path('post.html')
        self.images_destination = destination / Path('images')
        self.files_destination = destination / Path('files')
        self.external_videos_destination = destination / Path('external_videos')
        self.boosty_videos_destination = destination / Path('boosty_videos')
        self.audio_destination = destination / Path('audio')

    def _should_execute(
        self, post: Post, missing_parts: list[DownloadContentTypeFilter]
    ) -> bool:
        """Check if the post has any content matching the requested filters."""
        chunk_to_filter: dict[type, DownloadContentTypeFilter] = {
            PostDataChunkAudio: DownloadContentTypeFilter.audio,
            PostDataChunkBoostyVideo: DownloadContentTypeFilter.boosty_videos,
            PostDataChunkExternalVideo: DownloadContentTypeFilter.external_videos,
            PostDataChunkFile: DownloadContentTypeFilter.files,
            PostDataChunkText: DownloadContentTypeFilter.post_content,
            PostDataChunkTextualList: DownloadContentTypeFilter.post_content,
            PostDataChunkImage: DownloadContentTypeFilter.post_content,
        }

        for chunk in post.post_data_chunks:
            filter_type = chunk_to_filter.get(type(chunk))
            if filter_type and filter_type in missing_parts:
                return True
        return False

    # --------------------------------------------------------------------------
    # Main method do start the action

    async def execute(self) -> None:
        """
        Execute the use case to download a single post.

        Raises
        ------
        ApplicationCancelledError: If the download is cancelled by the user.
        ApplicationFailedDownloadError: If the download fails for any reason for a specific post.

        """
        post = map_post_dto_to_domain(
            self.post_dto, preferred_video_quality=self.context.preferred_video_quality
        )

        missing_parts: list[DownloadContentTypeFilter] = (
            self.context.post_cache.get_post_missing_parts(
                post_uuid=post.uuid,
                updated_at=post.updated_at,
                required=self.context.filters,
            )
        )

        if not missing_parts:
            self.context.progress_reporter.notice(
                'SKIP([bold]cached[/bold] and up-to-date): ' + self.destination.name
            )
            return

        if not self._should_execute(post, missing_parts):
            self.context.progress_reporter.notice(
                'SKIP ([bold]no content[/bold] matching selected filters): '
                + self.destination.name
            )
            return

        self.destination.mkdir(parents=True, exist_ok=True)
        post_task_id = self._start_post_task(post)
        try:
            post_html: list[HtmlGenChunk] = []

            for chunk in post.post_data_chunks:
                html_chunk = await self._safely_process_chunk(
                    chunk, missing_parts, post
                )
                if html_chunk:
                    post_html.append(html_chunk)

                self._update_post_task(post_task_id)

            if DownloadContentTypeFilter.post_content in missing_parts:
                try:
                    render_html_to_file(post_html, out_path=self.post_file_path)
                except CancelledError:
                    self.post_file_path.unlink(missing_ok=True)
                    raise

            self.context.post_cache.cache_post(
                post.uuid, post.updated_at, missing_parts
            )
            self.context.post_cache.commit()
            self.context.progress_reporter.success(
                f'Finished:  {self.destination.name}'
            )
        finally:
            self.context.progress_reporter.complete_task(post_task_id)

    def _start_post_task(self, post: Post) -> uuid.UUID:
        return self.context.progress_reporter.create_task(
            f'[bold]POST: {post.title}[/bold]',
            total=len(post.post_data_chunks),
            indent_level=1,
        )

    def _update_post_task(self, post_task_id: uuid.UUID) -> None:
        self.context.progress_reporter.update_task(
            post_task_id,
            advance=1,
        )

    async def _safely_process_chunk(
        self,
        chunk: PostDataAllChunks,
        missing_parts: list[DownloadContentTypeFilter],
        post: Post,
    ) -> HtmlGenChunk | None:
        """
        Safely process a chunk of post data and return the HTML representation if applicable.

        Handles exceptions and ensures that the post task is updated correctly.
        """
        # Centralized error handling to transform low level exceptions to application level
        try:
            return await self._process_chunk(chunk, missing_parts)
        # KeyboardInterrupt while downloading file
        except DownloadCancelledError as e:
            if e.file:
                e.file.unlink(missing_ok=True)
            raise ApplicationCancelledError(post_uuid=post.uuid) from e
        # KeyboardInterrupt while downloading external video
        except ExtVideoInterruptedByUserError as e:
            raise ApplicationCancelledError(post_uuid=post.uuid) from e
        # KeyboardInterrupt during asyncio tasks (general case)
        except CancelledError as e:
            raise ApplicationCancelledError(post_uuid=post.uuid) from e
        # Error while downloading file (e.g. boosty video / files / images)
        except DownloadError as e:
            if e.file:
                e.file.unlink(missing_ok=True)
            await self.context.failed_logger.add_error(
                f'{_form_post_url(username=self.context.author_name, post_id=post.uuid)} - {e.resource_url}',
                f'Failed to download file ({e.file}): {e.message}',
            )
            raise ApplicationFailedDownloadError(
                post_uuid=post.uuid,
                message=f"Couldn't download resource: {e.message}",
                resource=e.file.name if e.file else 'Unknown name',
            ) from e
        # Error while downloading external video
        except ExtVideoInfoError as e:
            await self.context.failed_logger.add_error(
                f'{_form_post_url(username=self.context.author_name, post_id=post.uuid)} - {e.video_url}',
                "External video unavailable or access restricted (can't get info)",
            )
            raise ApplicationFailedDownloadError(
                post_uuid=post.uuid,
                message='External video unavailable or access restricted.',
                resource='UNAVAILABLE',
            ) from e
        except ExtVideoDownloadError as e:
            await self.context.failed_logger.add_error(
                f'{_form_post_url(username=self.context.author_name, post_id=post.uuid)} - {e.video_url}',
                'External video download failed',
            )
            raise ApplicationFailedDownloadError(
                post_uuid=post.uuid,
                message="Couldn't download external video",
                resource=e.video_url,
            ) from e

    async def _process_chunk(  # noqa: C901, PLR0911
        self,
        chunk: PostDataAllChunks,
        missing_parts: list[DownloadContentTypeFilter],
    ) -> HtmlGenChunk | None:
        should_generate_post = DownloadContentTypeFilter.post_content in missing_parts
        should_download_files = DownloadContentTypeFilter.files in missing_parts
        should_download_videos = (
            DownloadContentTypeFilter.boosty_videos in missing_parts
        )
        should_download_ext_videos = (
            DownloadContentTypeFilter.external_videos in missing_parts
        )
        should_download_audio = DownloadContentTypeFilter.audio in missing_parts

        # ----------------------------------------------------------------------
        # Post Content (Text / List / Image) processing
        if isinstance(chunk, PostDataChunkText) and should_generate_post:
            return convert_text_to_html(chunk)
        if isinstance(chunk, PostDataChunkTextualList) and should_generate_post:
            return convert_list_to_html(chunk)
        if isinstance(chunk, PostDataChunkImage) and should_generate_post:
            saved_as = await self.download_image(image=chunk)
            return HtmlGenImage(url=str(saved_as), alt=saved_as.name)
        # ----------------------------------------------------------------------
        # Boosty Video
        if isinstance(chunk, PostDataChunkBoostyVideo) and should_download_videos:
            saved_as = await self.download_boosty_video(chunk)
            if DownloadContentTypeFilter.post_content in missing_parts:
                return convert_video_to_html(src=str(saved_as), title=chunk.title)
        # ----------------------------------------------------------------------
        # External Video
        elif (
            isinstance(chunk, PostDataChunkExternalVideo) and should_download_ext_videos
        ):
            saved_as = await self.download_external_videos(external_video=chunk)
            if DownloadContentTypeFilter.post_content in missing_parts:
                return convert_video_to_html(src=str(saved_as), title=saved_as.name)
        # ----------------------------------------------------------------------
        # Files
        elif isinstance(chunk, PostDataChunkFile) and should_download_files:
            await self.download_files(file=chunk)
        # ----------------------------------------------------------------------
        # Audio
        elif isinstance(chunk, PostDataChunkAudio) and should_download_audio:
            saved_as = await self.download_audio(audio=chunk)
            if DownloadContentTypeFilter.post_content in missing_parts:
                return convert_audio_to_html(src=str(saved_as), title=chunk.title)
        return None

    # --------------------------------------------------------------------------
    # Helper downloading methods

    async def _download_with_progress(
        self,
        url: str,
        filename: str,
        destination: Path,
        task_label: str,
        *,
        guess_extension: bool = True,
    ) -> Path:
        """Download a file with progress tracking and return path relative to post directory."""
        destination.mkdir(parents=True, exist_ok=True)
        task_id = self.context.progress_reporter.create_task(task_label, indent_level=2)

        def update_progress(status: DownloadingStatus) -> None:
            downloaded = human_readable_size(status.total_downloaded_bytes)
            total = human_readable_size(status.total_bytes)
            self.context.progress_reporter.update_task(
                task_id,
                advance=status.downloaded_bytes,
                total=status.total_bytes,
                description=f'{task_label} [{downloaded} / {total}]',
            )

        try:
            path = await download_file(
                DownloadFileConfig(
                    session=self.context.downloader_session,
                    url=url,
                    filename=filename,
                    destination=destination,
                    guess_extension=guess_extension,
                    on_status_update=update_progress,
                )
            )
        finally:
            self.context.progress_reporter.complete_task(task_id)

        return path.relative_to(self.post_file_path.parent)

    async def download_boosty_video(self, video: PostDataChunkBoostyVideo) -> Path:
        """Download a Boosty video and return the path to the saved file."""
        return await self._download_with_progress(
            url=video.url,
            filename=video.title,
            destination=self.boosty_videos_destination,
            task_label=f'[bold orange]Boosty Video[/bold orange]: {video.title}',
        )

    async def download_external_videos(
        self, external_video: PostDataChunkExternalVideo
    ) -> Path:
        """Download an external video using yt-dlp."""
        self.external_videos_destination.mkdir(parents=True, exist_ok=True)
        task_id = self.context.progress_reporter.create_task(
            f'External video: {external_video.url}', indent_level=2
        )

        def update_progress(status: ExternalVideoDownloadStatus) -> None:
            downloaded = human_readable_size(status.downloaded_bytes)
            total = human_readable_size(status.total_bytes)
            self.context.progress_reporter.update_task(
                task_id,
                advance=status.delta_bytes,
                total=status.total_bytes,
                description=f'External video [{downloaded} / {total}]: {external_video.url}',
            )

        try:
            path = self.context.external_videos_downloader.download_video(
                url=external_video.url,
                destination_directory=self.external_videos_destination,
                progress_hook=update_progress,
            )
        finally:
            self.context.progress_reporter.complete_task(task_id)

        return path.relative_to(self.external_videos_destination.parent)

    async def download_files(self, file: PostDataChunkFile) -> Path:
        """Download a file attachment."""
        return await self._download_with_progress(
            url=file.url,
            filename=file.filename,
            destination=self.files_destination,
            task_label=f'File: {file.filename}',
        )

    async def download_image(self, image: PostDataChunkImage) -> Path:
        """Download an image."""
        return await self._download_with_progress(
            url=image.url,
            filename=URL(image.url).name,
            destination=self.images_destination,
            task_label=f'Image: {URL(image.url).name}',
            guess_extension=False,
        )

    async def download_audio(self, audio: PostDataChunkAudio) -> Path:
        return await self._download_with_progress(
            url=audio.url,
            filename=audio.title,
            destination=self.audio_destination,
            task_label=f'Audio: {audio.title}',
            guess_extension=False,
        )
