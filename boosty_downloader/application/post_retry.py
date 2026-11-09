"""Per-post retry policy: attempts, backoff and one expired-link refresh."""

import asyncio
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.post_access import observe_post_access
from boosty_downloader.application.post_download_state import PostRunProgress
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.domain.post_folder import compose_post_directory_name
from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPIClient,
    BoostyAPIError,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.file_downloader import is_expired_link_error
from boosty_downloader.infrastructure.path_sanitizer import (
    PATH_TOO_LONG_HINT,
    is_path_too_long_error,
)

MAX_DOWNLOAD_ATTEMPTS = 5


class PostOutcome(Enum):
    """Outcome of one post within the full-download run."""

    downloaded = auto()
    failed = auto()
    # A piece of the post is gone for good (a deleted video): the post is
    # not complete, but nothing points at the disk or the network.
    unavailable = auto()


@dataclass
class _PostAttempt:
    """Everything one download try needs; rebuilt when links are refreshed."""

    post_dto: PostDTO
    use_case: DownloadSinglePostUseCase
    # A refresh is spent even when it fails: the second 400 on fresh
    # links means the problem is not expiry.
    refreshed: bool = False

    @property
    def folder_name(self) -> str:
        """Use the located folder, including a retained folder after title changes."""
        return self.use_case.destination.name


class PostDownloadRetrier:
    """
    Download one post, absorbing failures that retrying can heal.

    Owns the attempt budget, the backoff between attempts and the single
    re-fetch of a post whose signed links expired mid-run.
    """

    def __init__(
        self,
        author_name: str,
        boosty_api: BoostyAPIClient,
        destination: Path,
        download_context: DownloadContext,
    ) -> None:
        self.author_name = author_name
        self.boosty_api = boosty_api
        self.destination = destination
        self.context = download_context

    async def observe_access(self, post: PostDTO, failed_posts: list[str]) -> bool:
        """Contain an observation failure like any other failure of this post."""
        try:
            await observe_post_access(self.context, post)
        except ApplicationCancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - per-post storage failure boundary
            folder = compose_post_directory_name(post.title, post.created_at, post.id)
            await self._skip_unexpected(folder, post.id, failed_posts, error)
            return False
        return True

    async def download(self, post_dto: PostDTO, failed_posts: list[str]) -> PostOutcome:
        """Run the retry policy; every exit path is an explicit outcome."""
        delay = 1.0
        attempt_state = self._build_attempt(post_dto)
        for attempt in range(1, MAX_DOWNLOAD_ATTEMPTS + 1):
            try:
                await attempt_state.use_case.execute()
            except ApplicationCancelledError:  # noqa: PERF203 - per-post isolation is the point here
                raise
            except ApplicationFailedDownloadError as e:
                fresh_attempt = None
                if attempt < MAX_DOWNLOAD_ATTEMPTS:
                    fresh_attempt = await self._refresh_expired_links(attempt_state, e)
                if fresh_attempt is not None:
                    attempt_state = fresh_attempt
                    continue
                if not e.retryable:
                    outcome = self._skip_unavailable(
                        attempt_state.folder_name, failed_posts, e
                    )
                    return await self._finish(attempt_state, outcome, failed_posts)
                if attempt == MAX_DOWNLOAD_ATTEMPTS:
                    outcome = self._skip_after_retries(
                        attempt_state.folder_name, failed_posts, e, attempts=attempt
                    )
                    return await self._finish(attempt_state, outcome, failed_posts)
                delay = await self._wait_before_retry(
                    attempt_state.folder_name, e, attempt=attempt, delay=delay
                )
            # Containment: an unexpected error (e.g. OSError from a too
            # long post title) skips this post, never the whole run.
            # Must stay below the cancellation re-raise, or Ctrl+C
            # would be swallowed here.
            except Exception as e:  # noqa: BLE001
                outcome = await self._skip_unexpected(
                    attempt_state.folder_name,
                    attempt_state.post_dto.id,
                    failed_posts,
                    e,
                )
                return await self._finish(attempt_state, outcome, failed_posts)
            else:
                return await self._finish(
                    attempt_state, PostOutcome.downloaded, failed_posts
                )
        return await self._finish(attempt_state, PostOutcome.failed, failed_posts)

    def _build_attempt(
        self, post_dto: PostDTO, progress: PostRunProgress | None = None
    ) -> _PostAttempt:
        """Compose the post folder name and the use case that downloads into it."""
        folder_name = compose_post_directory_name(
            post_dto.title, post_dto.created_at, post_dto.id
        )
        use_case = DownloadSinglePostUseCase(
            destination=self.destination / folder_name,
            post_dto=post_dto,
            download_context=self.context,
            run_progress=progress,
        )
        return _PostAttempt(post_dto=post_dto, use_case=use_case)

    async def _refresh_expired_links(
        self, attempt_state: _PostAttempt, error: ApplicationFailedDownloadError
    ) -> _PostAttempt | None:
        """Rebuild the attempt with fresh signed urls; None means retry as usual."""
        if attempt_state.refreshed or not is_expired_link_error(error):
            return None
        attempt_state.refreshed = True
        self.context.progress_reporter.warn(
            'Signed links look expired, refreshing the post: '
            + attempt_state.folder_name
        )
        try:
            fresh_dto = await self.boosty_api.get_single_post(
                self.author_name, attempt_state.post_dto.id
            )
        except BoostyAPIError:
            # The normal retry/skip path handles the original error.
            return None
        fresh_attempt = self._build_attempt(
            fresh_dto, attempt_state.use_case.run_progress
        )
        fresh_attempt.refreshed = True
        return fresh_attempt

    async def _finish(
        self, state: _PostAttempt, outcome: PostOutcome, failed_posts: list[str]
    ) -> PostOutcome:
        try:
            state.use_case.finalize()
        except asyncio.CancelledError as error:
            raise ApplicationCancelledError(state.post_dto.id) from error
        except Exception as error:  # noqa: BLE001 - terminal per-post failure boundary
            message = f'Could not render complete post page: {error}'
            self.context.progress_reporter.error(message)
            failed_posts.append(f'{state.folder_name} ({message})')
            await self._log_unexpected(state.post_dto.id, message)
            return PostOutcome.failed
        if outcome is PostOutcome.downloaded:
            state.use_case.record_success()
        return outcome

    async def _log_unexpected(self, post_id: str, message: str) -> None:
        try:
            await self.context.failed_logger.add_error(post_id, message)
        except OSError as error:
            self.context.progress_reporter.warn(f'Could not write failure log: {error}')

    def _skip_after_retries(
        self,
        folder_name: str,
        failed_posts: list[str],
        error: ApplicationFailedDownloadError,
        *,
        attempts: int,
    ) -> PostOutcome:
        """Give up on a post whose known failure survived all retries."""
        hint = f' Hint: {PATH_TOO_LONG_HINT}.' if is_path_too_long_error(error) else ''
        failed_posts.append(f'{folder_name} ({error.message}){hint}')
        self.context.progress_reporter.error(
            f'Skip post after {attempts} failed attempts: '
            f'{folder_name} ({error.message}){hint}'
        )
        return PostOutcome.failed

    def _skip_unavailable(
        self,
        folder_name: str,
        failed_posts: list[str],
        error: ApplicationFailedDownloadError,
    ) -> PostOutcome:
        """Give up on a post at once: a piece that is gone for good does not come back."""
        failed_posts.append(f'{folder_name} ({error.message})')
        self.context.progress_reporter.error(
            f'Skip post, retrying will not help: {folder_name} ({error.message})'
        )
        return PostOutcome.unavailable

    async def _skip_unexpected(
        self,
        folder_name: str,
        post_id: str,
        failed_posts: list[str],
        error: Exception,
    ) -> PostOutcome:
        """Give up on a post immediately: unexpected errors do not heal by retrying."""
        hint = f' Hint: {PATH_TOO_LONG_HINT}.' if is_path_too_long_error(error) else ''
        failed_posts.append(f'{folder_name} ({error}){hint}')
        self.context.progress_reporter.error(
            f'Skip post after unexpected error: {folder_name} ({error}){hint}'
        )
        await self._log_unexpected(post_id, f'Unexpected error: {error}{hint}')
        return PostOutcome.failed

    async def _wait_before_retry(
        self,
        folder_name: str,
        error: ApplicationFailedDownloadError,
        *,
        attempt: int,
        delay: float,
    ) -> float:
        """Report the failed attempt, back off, and return the next delay."""
        self.context.progress_reporter.warn(
            f'Attempt {attempt} failed for post: {folder_name} ({error.message}), RESOURCE: ({error.resource})'
        )
        self.context.progress_reporter.warn(
            f'Retrying in {delay:.1f}s... ({error.message})'
        )
        await asyncio.sleep(delay)
        return min(delay * 1.5, 10.0)
