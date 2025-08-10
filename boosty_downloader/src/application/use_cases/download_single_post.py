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

    def _should_execute(
        self, post: Post, filters: list[DownloadContentTypeFilter]
    ) -> bool:
        # Check if any of the filters match the content type
        post_has_boosty_videos = any(
            isinstance(chunk, PostDataChunkBoostyVideo)
            for chunk in post.post_data_chunks
        )
        post_has_external_videos = any(
            isinstance(chunk, PostDataChunkExternalVideo)
            for chunk in post.post_data_chunks
        )
        post_has_files = any(
            isinstance(chunk, PostDataChunkFile) for chunk in post.post_data_chunks
        )
        post_has_post_content = any(
            isinstance(
                chunk, PostDataChunkText | PostDataChunkTextualList | PostDataChunkImage
            )
            for chunk in post.post_data_chunks
        )

        want_boosty_videos = DownloadContentTypeFilter.boosty_videos in filters
        want_external_videos = DownloadContentTypeFilter.external_videos in filters
        want_files = DownloadContentTypeFilter.files in filters
        want_post_content = DownloadContentTypeFilter.post_content in filters

        # Start use case only if we *actually* have a job to do
        return (
            (want_boosty_videos and post_has_boosty_videos)
            or (want_external_videos and post_has_external_videos)
            or (want_files and post_has_files)
            or (want_post_content and post_has_post_content)
        )

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
            self.context.post_cache.get_missing_parts(
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

            self.context.post_cache.cache(post.uuid, post.updated_at, missing_parts)
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

    async def _process_chunk(
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
        return None

    # --------------------------------------------------------------------------
    # Helper downloading methods

    async def download_boosty_video(
        self,
        boosty_video: PostDataChunkBoostyVideo,
    ) -> Path:
        """Download a Boosty video and returns the path to the saved file."""
        self.boosty_videos_destination.mkdir(parents=True, exist_ok=True)

        download_task_id = self.context.progress_reporter.create_task(
            f'[bold orange]Boosty video[/bold orange]: {boosty_video.title}',
            indent_level=2,  # Nesting: page/post/video = 0/1/2
        )

        def update_progress(status: DownloadingStatus) -> None:
            human_downloaded_size = human_readable_size(status.total_downloaded_bytes)
            human_total_size = human_readable_size(status.total_bytes)

            self.context.progress_reporter.update_task(
                download_task_id,
                advance=status.downloaded_bytes,
                total=status.total_bytes,
                description=f'[bold orange]Boosty Video[/bold orange] [{human_downloaded_size} / {human_total_size}]: {boosty_video.title} ',
            )

        dl_config = DownloadFileConfig(
            session=self.context.downloader_session,
            url=boosty_video.url,
            filename=boosty_video.title,
            guess_extension=True,
            destination=self.boosty_videos_destination,
            on_status_update=update_progress,
        )

        try:
            downloaded_file_path = await download_file(dl_config)
        finally:
            self.context.progress_reporter.complete_task(download_task_id)

        return downloaded_file_path.relative_to(self.post_file_path.parent)

    async def download_external_videos(
        self, external_video: PostDataChunkExternalVideo
    ) -> Path:
        self.external_videos_destination.mkdir(parents=True, exist_ok=True)

        download_video_task_id = self.context.progress_reporter.create_task(
            f'Downloading external video: {external_video.url}',
            indent_level=2,  # Nesting: page/post/video = 0/1/2
        )

        def update_progress(status: ExternalVideoDownloadStatus) -> None:
            human_downloaded_size = human_readable_size(status.downloaded_bytes)
            human_total_size = human_readable_size(status.total_bytes)

            self.context.progress_reporter.update_task(
                download_video_task_id,
                advance=status.delta_bytes,
                total=status.total_bytes,
                description=f'Downloading external video [{human_downloaded_size} / {human_total_size}]: {external_video.url}',
            )

        try:
            downloaded_file_path = (
                self.context.external_videos_downloader.download_video(
                    url=external_video.url,
                    destination_directory=self.external_videos_destination,
                    progress_hook=update_progress,
                )
            )
        finally:
            self.context.progress_reporter.complete_task(download_video_task_id)

        return downloaded_file_path.relative_to(self.external_videos_destination.parent)

    async def download_files(self, file: PostDataChunkFile) -> Path:
        # Download them all with options of the class
        self.files_destination.mkdir(parents=True, exist_ok=True)

        download_task_id = self.context.progress_reporter.create_task(
            f'Downloading file: {file.filename}',
            indent_level=2,  # Nesting: page/post/file = 0/1/2
        )

        def update_progress(status: DownloadingStatus) -> None:
            human_downloaded_size = human_readable_size(status.total_downloaded_bytes)
            human_total_size = human_readable_size(status.total_bytes)

            self.context.progress_reporter.update_task(
                download_task_id,
                advance=status.downloaded_bytes,
                total=status.total_bytes,
                description=f'Downloading file [{human_downloaded_size} / {human_total_size}]: {file.filename}',
            )

        dl_config = DownloadFileConfig(
            session=self.context.downloader_session,
            url=file.url,
            filename=file.filename,
            guess_extension=True,
            destination=self.files_destination,
            on_status_update=update_progress,
        )

        try:
            downloaded_file_path = await download_file(dl_config)
        finally:
            self.context.progress_reporter.complete_task(download_task_id)

        return downloaded_file_path.relative_to(self.post_file_path.parent)

    async def download_image(self, image: PostDataChunkImage) -> Path:
        """Download an image and returns the path to the saved file."""
        self.images_destination.mkdir(parents=True, exist_ok=True)

        download_task_id = self.context.progress_reporter.create_task(
            f'Downloading image: {image.url}',
            indent_level=2,  # Nesting: page/post/image = 0/1/2
        )

        def update_progress(status: DownloadingStatus) -> None:
            human_downloaded_size = human_readable_size(status.total_downloaded_bytes)
            human_total_size = human_readable_size(status.total_bytes)

            self.context.progress_reporter.update_task(
                download_task_id,
                advance=status.downloaded_bytes,
                total=status.total_bytes,
                description=f'Downloading image [{human_downloaded_size} / {human_total_size}]: {image.url}',
            )

        dl_config = DownloadFileConfig(
            session=self.context.downloader_session,
            url=image.url,
            filename=URL(image.url).name,
            destination=self.images_destination,
            on_status_update=update_progress,
        )

        try:
            downloaded_file_path = await download_file(dl_config)
        finally:
            self.context.progress_reporter.complete_task(download_task_id)

        return downloaded_file_path.relative_to(self.post_file_path.parent)
