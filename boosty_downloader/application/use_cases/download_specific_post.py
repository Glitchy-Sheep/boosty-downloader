"""Use case for downloading a specific Boosty post by URL."""

from pathlib import Path
from typing import TYPE_CHECKING

from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.post_retry import PostOutcome
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
    compose_post_directory_name,
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
from boosty_downloader.infrastructure.path_sanitizer import (
    PATH_TOO_LONG_HINT,
    is_path_too_long_error,
)

if TYPE_CHECKING:
    from boosty_downloader.infrastructure.boosty_api.models.post.post import (
        PostDTO,
    )


class DownloadPostByUrlUseCase:
    """
    Handles downloading one Boosty post of the creator by its id.

    The post is requested directly by id - one API call, fresh signed urls.
    The caller has already read the id off the post url.
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
        self.destination = destination
        self.context = download_context

    async def execute(self) -> PostOutcome:
        """Find and download the post; the caller turns the outcome into an exit code."""
        post_uuid = self.post_id
        self.context.progress_reporter.info(
            f'Requesting the post with UUID: {post_uuid}...'
        )
        try:
            post = await self.boosty_api.get_single_post(
                self.context.author_name, post_uuid
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
                    SkippedPost(post_id=post_uuid, title='<unparsed>', errors=e.errors)
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
            return PostOutcome.failed

        return await self._download_post(post)

    async def _download_post(self, post: 'PostDTO') -> PostOutcome:
        """Download the found post and name how it went."""
        self.context.progress_reporter.success(
            f'Found post with UUID: {post.id}, starting download...'
        )

        summary = format_run_summary([], collect_unknown_content(post))
        if summary:
            self.context.progress_reporter.warn(summary)

        post_name = compose_post_directory_name(post.title, post.created_at, post.id)

        try:
            await DownloadSinglePostUseCase(
                post_dto=post,
                destination=self.destination / post_name,
                download_context=self.context,
            ).execute()
        except ApplicationFailedDownloadError as e:
            hint = f' Hint: {PATH_TOO_LONG_HINT}.' if is_path_too_long_error(e) else ''
            self.context.progress_reporter.error(
                f'Failed to download post: {e.message}, RESOURCE: ({e.resource}){hint}'
            )
            return PostOutcome.failed
        return PostOutcome.downloaded
