"""Execute exact media work and finalize one complete stored post page."""

from __future__ import annotations

from asyncio import CancelledError, Semaphore, Task, create_task, gather, wait
from datetime import datetime, timezone
from functools import partial
from typing import TYPE_CHECKING

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.filtering import (
    MEDIA_KIND_TO_FILTER,
    has_excluded_tag,
)
from boosty_downloader.application.mappers.post_mapper import map_post_dto_to_domain
from boosty_downloader.application.page_builder import build_post_page
from boosty_downloader.application.post_download_state import (
    PostDownloadState,
    PostRunProgress,
)
from boosty_downloader.application.post_preparation import PostPreparer
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
)
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.infrastructure.file_downloader import is_expired_link_error
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.html_generator.renderer import render_html_to_file
from boosty_downloader.infrastructure.human_readable_filesize import human_readable_size
from boosty_downloader.infrastructure.media_output_paths import (
    resolve_media_destination,
)
from boosty_downloader.infrastructure.post_media_downloader import (
    MediaDownloadError,
    PostMediaDownloader,
)

if TYPE_CHECKING:
    from pathlib import Path
    from uuid import UUID

    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.application.mappers.live_post import (
        DownloadableMediaChunk,
        LiveMedia,
    )
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
    from boosty_downloader.infrastructure.media_publication import PublishedFile
    from boosty_downloader.infrastructure.media_transfer import ReserveMediaPath
    from boosty_downloader.infrastructure.post_media_downloader import (
        MediaProgress,
        ProgressCallback,
    )

MEDIA_CONCURRENCY = 4


async def _stop_tasks(tasks: list[Task[None]]) -> None:
    for task in tasks:
        task.cancel()
    pending = set(tasks)
    while pending:
        try:
            _, pending = await wait(pending)
        except CancelledError:  # noqa: PERF203 - every cancellation must wait for workers
            continue
    for task in tasks:
        if not task.cancelled():
            task.exception()


class DownloadSinglePostUseCase:
    """Run one reconciled attempt; the retrier finalizes its page once."""

    def __init__(
        self,
        destination: Path,
        post_dto: PostDTO,
        download_context: DownloadContext,
        *,
        run_progress: PostRunProgress | None = None,
    ) -> None:
        self.destination = destination
        self.post_dto = post_dto
        self.context = download_context
        self.run_progress = run_progress or PostRunProgress()
        self._state: PostDownloadState | None = None
        self._needs_render = False
        self._unchanged = False
        self._excluded = False
        self._media = PostMediaDownloader(
            http=self.context.downloader_session,
            external_videos=self.context.external_videos_downloader,
        )

    async def execute(self) -> None:
        """Persist preparation, then fetch only selected missing piece identities."""
        self._needs_render = False
        self._excluded = has_excluded_tag(
            (tag.title for tag in self.post_dto.tags or ()), self.context.excluded_tags
        )
        if self._excluded:
            return
        if not self.post_dto.has_access:
            raise ApplicationFailedDownloadError(
                self.post_dto.id,
                self.post_dto.id,
                'Post access was lost',
                retryable=False,
            )
        preparer = PostPreparer(
            self.context.library_root,
            self.context.post_store,
            self.context.author_name,
            self.context.preferred_video_quality,
        )
        prepared = preparer.prepare(
            self.post_dto,
            self.context.filters,
            datetime.now(timezone.utc),
            checked_unavailable_ids=self.run_progress.checked_unavailable_ids,
        )
        self.destination = self.context.library_root / prepared.folder
        state = PostDownloadState(
            self.context.library_root,
            self.context.post_store,
            prepared,
            self.run_progress,
        )
        self._state = state
        self.context.post_store.clear_locked_post(
            self.context.author_name, self.post_dto.id
        )
        self._warn_incomplete()
        self._unchanged = not prepared.needs_update
        if prepared.needs_update:
            state.save_initial()
            self._needs_render = True
        post_task = self.context.progress_reporter.create_task(
            f'[bold]POST: {self.post_dto.title}[/bold]',
            total=len(prepared.reconciliation.download_ids),
            indent_level=1,
        )
        try:
            await self._download_selected(
                state,
                prepared.live.media,
                prepared.reconciliation.download_ids,
                post_task,
            )
            self._raise_unavailable(state)
        finally:
            self.context.progress_reporter.complete_task(post_task)

    def finalize(self) -> None:
        """Render current complete state after the terminal attempt outcome."""
        if not self._needs_render or self._state is None:
            return
        record = self._state.record
        render_html_to_file(
            build_post_page(record),
            out_path=resolve_media_destination(
                self.context.library_root, self._state.folder, 'post.html'
            ),
            page_title=record.post.title.strip() or self.destination.name,
        )
        self._state.mark_rendered(PAGE_TEMPLATE_VERSION)
        self._needs_render = False

    def record_success(self) -> None:
        """Count a post only after its terminal page outcome succeeded."""
        if self._excluded:
            self.context.run_statistics.posts_without_content += 1
            self.context.progress_reporter.info(
                f'Skip post (excluded tag): {self.post_dto.title}'
            )
        elif self._unchanged:
            self.context.run_statistics.posts_cached += 1
            self.context.progress_reporter.notice(
                'SKIP (unchanged): ' + self.destination.name
            )
        else:
            self.context.run_statistics.posts_downloaded += 1
            self.context.progress_reporter.success('Finished: ' + self.destination.name)

    def _warn_incomplete(self) -> None:
        mapped = map_post_dto_to_domain(
            self.post_dto, preferred_video_quality=self.context.preferred_video_quality
        )
        if mapped.incomplete_content_types:
            self.context.progress_reporter.warn(
                'Post has unfinished uploads (will retry next run): '
                + self.destination.name
            )
        for title in mapped.stream_only_videos:
            self.context.progress_reporter.warn(
                'Skip video (streams are not supported yet): '
                + (title.strip() or 'video')
            )

    async def _download_selected(
        self,
        state: PostDownloadState,
        media: dict[str, LiveMedia],
        ids: list[str],
        post_task: UUID,
    ) -> None:
        semaphore = Semaphore(MEDIA_CONCURRENCY)

        async def one(media_id: str) -> None:
            async with semaphore:
                await self._download_one(state, media_id, media[media_id])
            self.context.progress_reporter.update_task(post_task, advance=1)

        tasks = [create_task(one(media_id)) for media_id in ids]
        try:
            results = await gather(*tasks, return_exceptions=True)
        except CancelledError as error:
            await _stop_tasks(tasks)
            raise ApplicationCancelledError(self.post_dto.id) from error
        failures: list[ApplicationFailedDownloadError] = []
        for result in results:
            if isinstance(result, (CancelledError, ApplicationCancelledError)):
                raise ApplicationCancelledError(self.post_dto.id) from result
            if isinstance(result, ApplicationFailedDownloadError):
                failures.append(result)
            elif isinstance(result, BaseException):
                raise result
        if failures:
            raise _retry_failure(failures)

    async def _download_one(
        self, state: PostDownloadState, media_id: str, media: LiveMedia
    ) -> None:
        chunk = media.download
        if chunk is None:
            return
        task_id = self.context.progress_reporter.create_task(
            _media_label(chunk), total=media.expected_size, indent_level=2
        )

        def on_progress(progress: MediaProgress) -> None:
            self.context.progress_reporter.update_task(
                task_id,
                advance=progress.delta_bytes,
                total=progress.total_bytes,
                description=f'{_media_label(chunk)} [{human_readable_size(progress.downloaded_bytes)} / {human_readable_size(progress.total_bytes)}]',
            )

        try:
            result = await self._fetch(
                chunk, on_progress, partial(state.reserve, media_id)
            )
        except CancelledError as error:
            raise ApplicationCancelledError(self.post_dto.id) from error
        except MediaDownloadError as error:
            state.fail(media_id, error.message, unavailable=not error.retryable)
            await self._log_media_failure(error)
            raise ApplicationFailedDownloadError(
                self.post_dto.id,
                error.resource_url,
                f"Couldn't download resource: {error.message}",
                retryable=error.retryable,
            ) from error
        else:
            if state.complete(media_id, result):
                self.context.run_statistics.add_media(
                    _media_counts(media.kind), result.size
                )
        finally:
            self.context.progress_reporter.complete_task(task_id)

    async def _log_media_failure(self, error: MediaDownloadError) -> None:
        try:
            await self.context.failed_logger.add_error(
                f'https://boosty.to/{self.context.author_name}/posts/{self.post_dto.id} - {error.resource_url}',
                error.message,
            )
        except OSError as log_error:
            self.context.progress_reporter.warn(
                f'Could not write failure log: {log_error}'
            )

    async def _fetch(
        self,
        chunk: DownloadableMediaChunk,
        progress: ProgressCallback,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        match chunk:
            case PostDataChunkImage():
                return await self._media.download_image(
                    chunk, progress, reserve=reserve
                )
            case PostDataChunkFile():
                return await self._media.download_file(chunk, progress, reserve=reserve)
            case PostDataChunkAudio():
                return await self._media.download_audio(
                    chunk, progress, reserve=reserve
                )
            case PostDataChunkBoostyVideo():
                return await self._media.download_boosty_video(
                    chunk, progress, reserve=reserve
                )
            case PostDataChunkExternalVideo():
                return await self._media.download_external_video(
                    chunk, progress, reserve=reserve
                )

    def _raise_unavailable(self, state: PostDownloadState) -> None:
        for media_id, entry in state.record.media.items():
            if (
                entry.status is MediaStatus.unavailable
                and entry.removed_at is None
                and media_id in self.run_progress.checked_unavailable_ids
                and MEDIA_KIND_TO_FILTER[entry.kind] in self.context.filters
            ):
                raise ApplicationFailedDownloadError(
                    self.post_dto.id,
                    media_id,
                    entry.error or 'Media unavailable',
                    retryable=False,
                )


def _retry_failure(
    failures: list[ApplicationFailedDownloadError],
) -> ApplicationFailedDownloadError:
    for failure in failures:
        if failure.retryable and is_expired_link_error(failure):
            return failure
    return next((failure for failure in failures if failure.retryable), failures[0])


def _media_label(chunk: DownloadableMediaChunk) -> str:
    match chunk:
        case PostDataChunkImage():
            return 'Image'
        case PostDataChunkFile():
            return f'File: {chunk.filename}'
        case PostDataChunkAudio():
            return f'Audio: {chunk.title}'
        case PostDataChunkBoostyVideo():
            return f'Boosty video: {chunk.title}'
        case PostDataChunkExternalVideo():
            return f'External video: {chunk.url}'


def _media_counts(kind: MediaKind) -> MediaCounts:
    match kind:
        case MediaKind.image:
            return MediaCounts(images=1)
        case MediaKind.file:
            return MediaCounts(files=1)
        case MediaKind.audio:
            return MediaCounts(audio=1)
        case MediaKind.boosty_video:
            return MediaCounts(boosty_videos=1)
        case MediaKind.external_video:
            return MediaCounts(external_videos=1)
