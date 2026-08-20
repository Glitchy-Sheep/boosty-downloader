"""Implements the use case for downloading all posts from a Boosty author, applying filters and caching as needed."""

from pathlib import Path
from typing import TYPE_CHECKING

from boosty_downloader.application.di.download_context import DownloadContext
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationTooManyFailuresError,
)
from boosty_downloader.application.failure_streak import FailureStreakBreaker
from boosty_downloader.application.post_retry import (
    PostDownloadRetrier,
    PostOutcome,
)
from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPIClient,
)
from boosty_downloader.infrastructure.boosty_api.models.unknown_content import (
    UnknownContent,
    collect_unknown_content,
)
from boosty_downloader.infrastructure.boosty_api.utils.validation_errors import (
    format_run_summary,
    format_skipped_post,
)

# Failures of posts in a row, without a single success in between.
# Scattered failures are per-post problems; a streak like this almost
# always means a systemic cause - the run stops instead of grinding.
CONSECUTIVE_FAILURES_LIMIT = 5

if TYPE_CHECKING:
    from boosty_downloader.infrastructure.boosty_api.models.post.posts_request import (
        PostsResponse,
        SkippedPost,
    )


class DownloadAllPostUseCase:
    """
    Use case for downloading all user's posts.

    This class encapsulates the logic required to download all posts from a source.
    Initialize the use case and call its methods to perform the download operation.

    All the downloaded content parts will be saved under the specified destination path.
    """

    def __init__(
        self,
        author_name: str,
        boosty_api: BoostyAPIClient,
        destination: Path,
        download_context: DownloadContext,
        *,
        skip_all_failures: bool = False,
    ) -> None:
        self.author_name = author_name

        self.boosty_api = boosty_api
        self.destination = destination
        self.context = download_context
        self.skip_all_failures = skip_all_failures
        self._post_retrier = PostDownloadRetrier(
            author_name=author_name,
            boosty_api=boosty_api,
            destination=destination,
            download_context=download_context,
        )

    def _note_page_anomalies(
        self,
        page: 'PostsResponse',
        all_skipped: list['SkippedPost'],
        unknown_content: set[UnknownContent],
    ) -> None:
        """Warn about skipped posts and collect everything unknown for the summary."""
        all_skipped.extend(page.skipped_posts)
        for post_dto in page.posts:
            unknown_content |= collect_unknown_content(post_dto)
        for skipped in page.skipped_posts:
            self.context.progress_reporter.warn(format_skipped_post(skipped))

    async def execute(self) -> None:
        posts_iterator = self.boosty_api.iterate_over_posts(
            author_name=self.author_name
        )

        current_page = 0
        processed_ok = 0
        all_skipped: list[SkippedPost] = []
        failed_posts: list[str] = []
        unknown_content: set[UnknownContent] = set()
        # --skip-all-failures turns the breaker off: posts keep skipping
        # without limit, the run always reaches the end.
        breaker = FailureStreakBreaker(
            threshold=None if self.skip_all_failures else CONSECUTIVE_FAILURES_LIMIT
        )

        async for page in posts_iterator:
            count = len(page.posts)
            current_page += 1

            self._note_page_anomalies(page, all_skipped, unknown_content)

            page_task_id = self.context.progress_reporter.create_task(
                f'Got new posts: [{count}]',
                total=count,
                indent_level=0,  # Each page prints without indentation
            )

            for post_dto in page.posts:
                if not post_dto.has_access:
                    self.context.progress_reporter.warn(
                        f'Skip post ([red]no access to content[/red]): {post_dto.title}'
                    )
                    continue

                self.context.progress_reporter.update_task(
                    page_task_id,
                    advance=1,
                    description=f'Processing page [bold]{current_page}[/bold]',
                )

                outcome = await self._post_retrier.download(post_dto, failed_posts)
                if outcome is PostOutcome.downloaded:
                    processed_ok += 1
                    breaker.record_success()
                elif breaker.record_failure():
                    self._report_systemic_stop(processed_ok)
                    self._print_run_summary(all_skipped, unknown_content, failed_posts)
                    raise ApplicationTooManyFailuresError(
                        streak=CONSECUTIVE_FAILURES_LIMIT
                    )

            self.context.progress_reporter.complete_task(page_task_id)
            self.context.progress_reporter.success(
                f'--- Finished page {current_page} ---'
            )

        self._print_run_summary(all_skipped, unknown_content, failed_posts)

    def _report_systemic_stop(self, processed_ok: int) -> None:
        self.context.progress_reporter.error(
            f'Stopped: {CONSECUTIVE_FAILURES_LIMIT} posts in a row failed - '
            'the cause looks systemic (disk, permissions, network), '
            'not post-specific.\n'
            f'Posts processed before stopping: {processed_ok}. '
            'Details: failed_downloads.log\n'
            'Fix the cause and run the same command again - '
            'downloaded posts are cached and will be skipped in seconds.'
        )

    def _print_run_summary(
        self,
        all_skipped: 'list[SkippedPost]',
        unknown_content: set[UnknownContent],
        failed_posts: list[str],
    ) -> None:
        summary = format_run_summary(all_skipped, unknown_content, failed_posts)
        if summary:
            self.context.progress_reporter.warn(summary)
