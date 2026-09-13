"""
Use case for downloading a single post from Boosty.

Orchestrates one post: map the API answer, ask the cache what is missing,
download the media in parallel, render post.html and remember what landed.
"""

from __future__ import annotations

from asyncio import CancelledError, Semaphore, Task, create_task, gather
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property, partial
from typing import TYPE_CHECKING

from yarl import URL

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.filtering import (
    CHUNK_TO_FILTER,
    post_has_content_for,
)
from boosty_downloader.application.mappers.html_converter import (
    convert_audio_to_html,
    convert_list_to_html,
    convert_text_to_html,
    convert_video_to_html,
)
from boosty_downloader.application.mappers.post_mapper import (
    PostMappingResult,
    map_post_dto_to_domain,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.infrastructure.html_generator import (
    HtmlGenChunk,
    HtmlGenImage,
)
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html_to_file,
)
from boosty_downloader.infrastructure.human_readable_filesize import (
    human_readable_size,
)
from boosty_downloader.infrastructure.path_sanitizer import (
    MAX_NAME_BYTES,
    sanitize_filename,
)
from boosty_downloader.infrastructure.post_media_downloader import (
    MediaDownloadError,
    PostMediaDownloader,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from datetime import datetime
    from pathlib import Path
    from uuid import UUID

    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.domain.post import Post, PostDataAllChunks
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
    from boosty_downloader.infrastructure.post_media_downloader import (
        MediaProgress,
        ProgressCallback,
    )


def _form_post_url(username: str, post_id: str) -> str:
    return f'https://boosty.to/{username}/posts/{post_id}'


# One post's media download in parallel. The CDN caps every single
# connection, and each cold small file pays seconds of request latency;
# four connections reclaim most of the channel without hammering the host.
MEDIA_CONCURRENCY = 4


async def _stop_tasks(tasks: list[Task[HtmlGenChunk | None]]) -> None:
    """Cancel the tasks and wait until every one of them has actually stopped."""
    for task in tasks:
        task.cancel()
    await gather(*tasks, return_exceptions=True)


@dataclass(frozen=True, slots=True)
class _ChunkFailure:
    """One chunk that could not be saved, with the content type it belongs to."""

    kind: DownloadContentTypeFilter
    error: ApplicationFailedDownloadError


@dataclass(frozen=True, slots=True)
class _ChunksOutcome:
    """What one pass over the post's chunks produced."""

    # Page elements of the chunks that made it, in the author's order.
    page: list[HtmlGenChunk]
    failures: list[_ChunkFailure]


# Chunks that are saved as files; text and lists go straight to the page.
MediaChunk = (
    PostDataChunkImage
    | PostDataChunkBoostyVideo
    | PostDataChunkExternalVideo
    | PostDataChunkFile
    | PostDataChunkAudio
)


def _page_element(chunk: MediaChunk, saved_as: Path) -> HtmlGenChunk | None:
    """Build the element post.html shows for a saved media file; attachments have none."""
    match chunk:
        case PostDataChunkImage():
            return HtmlGenImage(url=str(saved_as), alt=saved_as.name)
        case PostDataChunkBoostyVideo():
            return convert_video_to_html(src=str(saved_as), title=chunk.title)
        case PostDataChunkExternalVideo():
            return convert_video_to_html(src=str(saved_as), title=saved_as.name)
        case PostDataChunkAudio():
            return convert_audio_to_html(src=str(saved_as), title=chunk.title)
        case PostDataChunkFile():
            return None


def compose_post_directory_name(title: str, created_at: datetime, post_id: str) -> str:
    """
    One folder per post: 'YYYY-MM-DD - Title (id8)'.

    The id tail keeps two same-titled posts apart; the title is cut to
    fit the filesystem name limit, the date and the id always survive.
    """
    clean_title = title.strip() or 'No title'
    prefix = f'{created_at.date()} - '
    suffix = f' ({post_id[:8]})'
    budget = MAX_NAME_BYTES - len(prefix.encode('utf-8'))
    return prefix + sanitize_filename(clean_title, suffix=suffix, max_bytes=budget)


class DownloadSinglePostUseCase:
    """
    Download one post into its folder.

    Media chunks download in parallel through PostMediaDownloader; the page
    is rendered from the chunks of this run and the cache remembers which
    content types finished.
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
        self.post_file_path = destination / 'post.html'

        # Media of the current attempt, per content type. A type reaches the
        # run statistics once every chunk of it finished; a retry fetches
        # only the types that failed, so nothing is counted twice.
        self._attempt_media: defaultdict[DownloadContentTypeFilter, MediaCounts] = (
            defaultdict(MediaCounts)
        )
        self._attempt_bytes: defaultdict[DownloadContentTypeFilter, int] = defaultdict(
            int
        )

    @cached_property
    def _media(self) -> PostMediaDownloader:
        return PostMediaDownloader(
            http=self.context.downloader_session,
            external_videos=self.context.external_videos_downloader,
            post_dir=self.destination,
        )

    def _should_execute(
        self, post: Post, missing_parts: list[DownloadContentTypeFilter]
    ) -> bool:
        """Check if the post has any content matching the requested filters."""
        return post_has_content_for(post, missing_parts)

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
        self._attempt_media.clear()
        self._attempt_bytes.clear()
        mapping_result: PostMappingResult = map_post_dto_to_domain(
            self.post_dto, preferred_video_quality=self.context.preferred_video_quality
        )
        post = mapping_result.post

        if mapping_result.incomplete_content_types:
            self.context.progress_reporter.warn(
                f'Post has unfinished uploads (will retry next run): {self.destination.name}'
            )
        for video_title in mapping_result.stream_only_videos:
            self.context.progress_reporter.warn(
                'Skip video (streams are not supported yet): '
                + (video_title.strip() or 'video')
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
            self.context.run_statistics.posts_cached += 1
            return

        if not self._should_execute(post, missing_parts):
            self.context.progress_reporter.notice(
                'SKIP ([bold]no content[/bold] matching selected filters): '
                + self.destination.name
            )
            self.context.run_statistics.posts_without_content += 1
            return

        self.destination.mkdir(parents=True, exist_ok=True)
        post_task_id = self._start_post_task(post)

        try:
            outcome = await self._process_chunks_concurrently(
                post, missing_parts, post_task_id
            )
            failed_types = {failure.kind for failure in outcome.failures}
            if DownloadContentTypeFilter.post_content in missing_parts:
                # Attachments are not on the page; any other failed chunk
                # would leave a hole in it, so the page waits for the retry.
                if failed_types - {DownloadContentTypeFilter.files}:
                    failed_types.add(DownloadContentTypeFilter.post_content)
                else:
                    self._render_page(post, outcome.page)

            finished_types = [p for p in missing_parts if p not in failed_types]
            self._remember(post, finished_types, mapping_result)
            if outcome.failures:
                # The log already names every failed chunk; the retrier
                # comes back for the failed types only.
                raise outcome.failures[0].error

            self.context.progress_reporter.success(
                f'Finished:  {self.destination.name}'
            )
            self.context.run_statistics.posts_downloaded += 1
        finally:
            self.context.progress_reporter.complete_task(post_task_id)

    def _render_page(self, post: Post, page: list[HtmlGenChunk]) -> None:
        try:
            render_html_to_file(
                page,
                out_path=self.post_file_path,
                # Empty titles happen: the folder name always carries
                # the date, the title and the id.
                page_title=post.title.strip() or self.destination.name,
            )
        except CancelledError:
            self.post_file_path.unlink(missing_ok=True)
            raise

    def _remember(
        self,
        post: Post,
        finished_types: list[DownloadContentTypeFilter],
        mapping_result: PostMappingResult,
    ) -> None:
        """Cache the finished content types and count their media for the run."""
        cacheable = [
            p
            for p in finished_types
            if p not in mapping_result.incomplete_content_types
        ]
        if cacheable:
            self.context.post_cache.cache_post(post.uuid, post.updated_at, cacheable)
            self.context.post_cache.commit()
        for kind in finished_types:
            self.context.run_statistics.add_media(
                self._attempt_media[kind], self._attempt_bytes[kind]
            )

    async def _process_chunks_concurrently(
        self,
        post: Post,
        missing_parts: list[DownloadContentTypeFilter],
        post_task_id: UUID,
    ) -> _ChunksOutcome:
        """
        Download every chunk, MEDIA_CONCURRENCY at a time.

        One failed chunk does not stop the others: every chunk runs to its
        end, and the failures come back next to the page elements of the
        chunks that made it. An outer cancel stops all of them and surfaces
        as ApplicationCancelledError.
        """
        semaphore = Semaphore(MEDIA_CONCURRENCY)

        async def one_chunk(chunk: PostDataAllChunks) -> HtmlGenChunk | None:
            async with semaphore:
                html_chunk = await self._safely_process_chunk(
                    chunk, missing_parts, post
                )
            self._update_post_task(post_task_id)
            return html_chunk

        tasks = [create_task(one_chunk(chunk)) for chunk in post.post_data_chunks]
        try:
            results = await gather(*tasks, return_exceptions=True)
        except CancelledError as e:
            await _stop_tasks(tasks)
            raise ApplicationCancelledError(post_uuid=post.uuid) from e

        page: list[HtmlGenChunk] = []
        failures: list[_ChunkFailure] = []
        for chunk, result in zip(post.post_data_chunks, results, strict=True):
            match result:
                case ApplicationFailedDownloadError():
                    failures.append(_ChunkFailure(CHUNK_TO_FILTER[type(chunk)], result))
                case BaseException():
                    # Cancellation inside a chunk, or an unexpected error:
                    # not a per-chunk failure, the post as a whole stops.
                    raise result
                case None:
                    pass
                case _:
                    page.append(result)
        return _ChunksOutcome(page=page, failures=failures)

    def _start_post_task(self, post: Post) -> UUID:
        return self.context.progress_reporter.create_task(
            f'[bold]POST: {post.title}[/bold]',
            total=len(post.post_data_chunks),
            indent_level=1,
        )

    def _update_post_task(self, post_task_id: UUID) -> None:
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
        """Process one chunk; infrastructure failures become application errors."""
        try:
            return await self._process_chunk(chunk, missing_parts)
        except CancelledError as e:
            raise ApplicationCancelledError(post_uuid=post.uuid) from e
        except MediaDownloadError as e:
            resource = e.file.name if e.file else e.resource_url
            await self.context.failed_logger.add_error(
                f'{_form_post_url(username=self.context.author_name, post_id=post.uuid)} - {e.resource_url}',
                f'Failed to download {resource}: {e.message}',
            )
            raise ApplicationFailedDownloadError(
                post_uuid=post.uuid,
                message=f"Couldn't download resource: {e.message}",
                resource=resource,
            ) from e

    async def _process_chunk(
        self,
        chunk: PostDataAllChunks,
        missing_parts: list[DownloadContentTypeFilter],
    ) -> HtmlGenChunk | None:
        """Download the chunk when its content type is wanted; return its page element."""
        if CHUNK_TO_FILTER.get(type(chunk)) not in missing_parts:
            return None
        if isinstance(chunk, PostDataChunkText):
            return convert_text_to_html(chunk)
        if isinstance(chunk, PostDataChunkTextualList):
            return convert_list_to_html(chunk)
        saved_as = await self._download_media(chunk)
        # Media that is not part of the page this run still downloads;
        # it just gets no element in post.html.
        if DownloadContentTypeFilter.post_content not in missing_parts:
            return None
        return _page_element(chunk, saved_as)

    async def _download_media(self, chunk: MediaChunk) -> Path:
        """Save one media chunk under its own progress bar."""
        match chunk:
            case PostDataChunkImage():
                return await self._download(
                    f'Image: {URL(chunk.url).name}',
                    partial(self._media.download_image, chunk),
                    MediaCounts(images=1),
                    kind=DownloadContentTypeFilter.post_content,
                )
            case PostDataChunkBoostyVideo():
                return await self._download(
                    f'[bold orange]Boosty Video[/bold orange]: {chunk.title}',
                    partial(self._media.download_boosty_video, chunk),
                    MediaCounts(boosty_videos=1),
                    kind=DownloadContentTypeFilter.boosty_videos,
                )
            case PostDataChunkExternalVideo():
                return await self._download(
                    f'External video: {chunk.url}',
                    partial(self._media.download_external_video, chunk),
                    MediaCounts(external_videos=1),
                    kind=DownloadContentTypeFilter.external_videos,
                )
            case PostDataChunkFile():
                return await self._download(
                    f'File: {chunk.filename}',
                    partial(self._media.download_file, chunk),
                    MediaCounts(files=1),
                    kind=DownloadContentTypeFilter.files,
                )
            case PostDataChunkAudio():
                return await self._download(
                    f'Audio: {chunk.title}',
                    partial(self._media.download_audio, chunk),
                    MediaCounts(audio=1),
                    kind=DownloadContentTypeFilter.audio,
                )

    async def _download(
        self,
        label: str,
        download: Callable[[ProgressCallback], Awaitable[Path]],
        media: MediaCounts,
        *,
        kind: DownloadContentTypeFilter,
    ) -> Path:
        """Run one media download under its own progress bar; count it for its content type."""
        task_id = self.context.progress_reporter.create_task(label, indent_level=2)
        downloaded_bytes = 0

        def on_progress(progress: MediaProgress) -> None:
            nonlocal downloaded_bytes
            downloaded_bytes = progress.downloaded_bytes
            done = human_readable_size(progress.downloaded_bytes)
            total = human_readable_size(progress.total_bytes)
            self.context.progress_reporter.update_task(
                task_id,
                advance=progress.delta_bytes,
                total=progress.total_bytes,
                description=f'{label} [{done} / {total}]',
            )

        try:
            path = await download(on_progress)
        finally:
            self.context.progress_reporter.complete_task(task_id)

        self._attempt_media[kind] += media
        self._attempt_bytes[kind] += downloaded_bytes
        return path
