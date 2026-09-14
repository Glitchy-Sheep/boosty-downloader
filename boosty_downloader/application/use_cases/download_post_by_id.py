"""Use case for downloading one Boosty post of the creator by its id."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.post_retry import (
    PostDownloadRetrier,
    PostOutcome,
)
from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPIClient,
    BoostyAPINoPostError,
    BoostyAPIValidationError,
)
from boosty_downloader.infrastructure.boosty_api.models.post.posts_request import (
    SkippedPost,
)
from boosty_downloader.infrastructure.boosty_api.models.unknown_content import (
    collect_unknown_content,
)
from boosty_downloader.infrastructure.boosty_api.utils.validation_errors import (
    GITHUB_ISSUES_URL,
    format_run_summary,
    format_skipped_post,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.infrastructure.boosty_api.models.post.post import (
        PostDTO,
    )


class DownloadPostByIdUseCase:
    """
    Download one post of the creator by its id.

    One direct API call brings the post with fresh signed urls. The download
    itself goes through the same retrier as the full run: attempts with
    backoff, one refresh of expired links, containment of unexpected errors.
    """

    def __init__(
        self,
        post_id: str,
        boosty_api: BoostyAPIClient,
        destination: Path,
        download_context: DownloadContext,
    ) -> None:
        self.post_id = post_id
        self.boosty_api = boosty_api
        self.context = download_context
        self._post_retrier = PostDownloadRetrier(
            author_name=download_context.author_name,
            boosty_api=boosty_api,
            destination=destination,
            download_context=download_context,
        )

    async def execute(self) -> PostOutcome:
        """Find and download the post; the caller turns the outcome into an exit code."""
        self.context.progress_reporter.info(
            f'Requesting the post with UUID: {self.post_id}...'
        )
        try:
            post = await self.boosty_api.get_single_post(
                self.context.author_name, self.post_id
            )
        except BoostyAPINoPostError:
            self.context.progress_reporter.error(
                'Failed to find and download the specified post.'
            )
            return PostOutcome.failed
        except BoostyAPIValidationError as e:
            # The searched post exists but this client can't parse it -
            # a misleading "not found" would hide the real problem.
            self.context.progress_reporter.error(
                format_skipped_post(
                    SkippedPost(
                        post_id=self.post_id, title='<unparsed>', errors=e.errors
                    )
                )
            )
            self.context.progress_reporter.error(
                f'Please report this at {GITHUB_ISSUES_URL} '
                'so the client can be updated.'
            )
            return PostOutcome.failed

        if not post.has_access:
            self.context.progress_reporter.error(
                f'Skip post (no access to content): {post.title}'
            )
            self.context.run_statistics.posts_locked += 1
            return PostOutcome.failed

        return await self._download_post(post)

    async def _download_post(self, post: PostDTO) -> PostOutcome:
        """Download the found post and name how it went."""
        self.context.progress_reporter.success(
            f'Found post with UUID: {post.id}, starting download...'
        )
        failed_posts: list[str] = []
        outcome = await self._post_retrier.download(post, failed_posts)
        if outcome is PostOutcome.failed:
            self.context.run_statistics.posts_failed += 1

        summary = format_run_summary([], collect_unknown_content(post), failed_posts)
        if summary:
            self.context.progress_reporter.warn(summary)
        return outcome
