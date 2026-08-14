"""Use case for downloading a specific Boosty post by URL."""

from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from boosty_downloader.src.application.di.download_context import DownloadContext
from boosty_downloader.src.application.exceptions.application_errors import (
    ApplicationCancelledError,
)
from boosty_downloader.src.application.use_cases.check_total_posts import (
    BoostyAPIClient,
)
from boosty_downloader.src.application.use_cases.download_single_post import (
    ApplicationFailedDownloadError,
    DownloadSinglePostUseCase,
    compose_post_directory_name,
)
from boosty_downloader.src.infrastructure.boosty_api.models.unknown_content import (
    collect_unknown_content,
)
from boosty_downloader.src.infrastructure.boosty_api.utils.validation_errors import (
    GITHUB_ISSUES_URL,
    format_run_summary,
    format_skipped_post,
)
from boosty_downloader.src.infrastructure.path_sanitizer import (
    PATH_TOO_LONG_HINT,
    is_path_too_long_error,
)

if TYPE_CHECKING:
    from boosty_downloader.src.infrastructure.boosty_api.models.post.post import (
        PostDTO,
    )
    from boosty_downloader.src.infrastructure.boosty_api.models.post.posts_request import (
        PostsResponse,
    )


class _PostDownloadOutcome(Enum):
    """Outcome of downloading the found post."""

    downloaded = auto()
    failed = auto()
    cancelled = auto()


class DownloadPostByUrlUseCase:
    """
    Handles downloading a specific Boosty post given its URL.

    Right now it just iterates over the post and downloads it if UUID matches.
    Because I can't find a way to get post by URL directly at this moment.

    If you know how to do it, please open an issue on GitHub or PR with this functionality.
    """

    def __init__(
        self,
        post_url: str,
        boosty_api: BoostyAPIClient,
        destination: Path,
        download_context: DownloadContext,
    ) -> None:
        self.post_url = post_url
        self.boosty_api = boosty_api
        self.destination = destination
        self.context = download_context

    def extract_author_and_uuid_from_url(self) -> tuple[str | None, str | None]:
        """
        Parse Boosty post URL and returns (author_name, post_uuid) if possible.

        Expects URLs like: https://boosty.to/author_name/posts/post_uuid
        Returns None if parsing fails or URL is not Boosty.
        """
        url = self.post_url
        if 'boosty.to' not in url:
            self.context.progress_reporter.error(
                "Provided URL doesn't match Boosty format (https://boosty.to/...)"
            )
            return None, None
        try:
            parts = url.split('/')
            author = parts[3]
            post_uuid = parts[5].split('?')[0]
        except (IndexError, AttributeError):
            self.context.progress_reporter.error(
                'Failed to parse author or post UUID from the provided URL. '
            )
            return None, None
        else:
            return author, post_uuid

    def _report_if_target_skipped(self, page: 'PostsResponse', post_uuid: str) -> bool:
        """
        Tell the user when the searched post exists but this client can't parse it.

        A misleading "not found" would hide the real problem.
        """
        for skipped in page.skipped_posts:
            if skipped.post_id == post_uuid:
                self.context.progress_reporter.error(format_skipped_post(skipped))
                self.context.progress_reporter.error(
                    f'Please report this at {GITHUB_ISSUES_URL} '
                    'so the client can be updated.'
                )
                return True
        return False

    async def execute(self) -> None:
        author_name, post_uuid = self.extract_author_and_uuid_from_url()
        if not author_name or not post_uuid:
            self.context.progress_reporter.error(
                'Failed to extract author and UUID from the provided URL, aborting...'
            )
            return

        current_page = 0

        async for page in self.boosty_api.iterate_over_posts(
            author_name=author_name, posts_per_page=100
        ):
            current_page += 1
            self.context.progress_reporter.info(
                f'[Page({current_page})] Searching for the post with UUID: {post_uuid}... '
            )
            if self._report_if_target_skipped(page, post_uuid):
                return

            for post in page.posts:
                if post.id == post_uuid:
                    outcome = await self._download_post(post)
                    if outcome is _PostDownloadOutcome.downloaded:
                        return
                    # Note: cancel does not stop the search - it moves on
                    # like a failed download.

        self.context.progress_reporter.error(
            'Failed to find and download the specified post.'
        )

    async def _download_post(self, post: 'PostDTO') -> _PostDownloadOutcome:
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
        except ApplicationCancelledError:
            self.context.progress_reporter.warn('Download cancelled by user. Bye!')
            return _PostDownloadOutcome.cancelled
        except ApplicationFailedDownloadError as e:
            hint = f' Hint: {PATH_TOO_LONG_HINT}.' if is_path_too_long_error(e) else ''
            self.context.progress_reporter.error(
                f'Failed to download post: {e.message}, RESOURCE: ({e.resource}){hint}'
            )
            return _PostDownloadOutcome.failed
        return _PostDownloadOutcome.downloaded
