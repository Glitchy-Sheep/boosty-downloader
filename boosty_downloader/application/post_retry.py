"""Per-post retry policy: attempts, backoff and one expired-link refresh."""

import asyncio
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from boosty_downloader.application.di.download_context import DownloadContext
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
    compose_post_directory_name,
)
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


@dataclass
class _PostAttempt:
    """Everything one download try needs; rebuilt when links are refreshed."""

    post_dto: PostDTO
    use_case: DownloadSinglePostUseCase
    folder_name: str
    # A refresh is spent even when it fails: the second 400 on fresh
    # links means the problem is not expiry.
    refreshed: bool = False


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
                fresh_attempt = await self._refresh_expired_links(attempt_state, e)
                if fresh_attempt is not None:
                    attempt_state = fresh_attempt
                    continue
                if attempt == MAX_DOWNLOAD_ATTEMPTS:
                    return self._skip_after_retries(
                        attempt_state.folder_name, failed_posts, e, attempts=attempt
                    )
                delay = await self._wait_before_retry(
                    attempt_state.folder_name, e, attempt=attempt, delay=delay
                )
            # Containment: an unexpected error (e.g. OSError from a too
            # long post title) skips this post, never the whole run.
            # Must stay below the cancellation re-raise, or Ctrl+C
            # would be swallowed here.
            except Exception as e:  # noqa: BLE001
                return await self._skip_unexpected(
                    attempt_state.folder_name,
                    attempt_state.post_dto.id,
                    failed_posts,
                    e,
                )
            else:
                return PostOutcome.downloaded
        return PostOutcome.failed

    def _build_attempt(self, post_dto: PostDTO) -> _PostAttempt:
        """Compose the post folder name and the use case that downloads into it."""
        folder_name = compose_post_directory_name(
            post_dto.title, post_dto.created_at, post_dto.id
        )
        use_case = DownloadSinglePostUseCase(
            destination=self.destination / folder_name,
            post_dto=post_dto,
            download_context=self.context,
        )
        return _PostAttempt(
            post_dto=post_dto, use_case=use_case, folder_name=folder_name
        )

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
        fresh_attempt = self._build_attempt(fresh_dto)
        fresh_attempt.refreshed = True
        return fresh_attempt

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
        await self.context.failed_logger.add_error(
            post_id,
            f'Unexpected error: {error}{hint}',
        )
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
