"""Use case for downloading a specific Boosty post by URL."""

from pathlib import Path

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
)
from boosty_downloader.src.infrastructure.file_downloader import sanitize_string


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
            for post in page.posts:
                if post.id == post_uuid:
                    self.context.progress_reporter.success(
                        f'Found post with UUID: {post_uuid}, starting download...'
                    )

                    post_name = f'{post.created_at.date()} - {post.title}'
                    post_name = sanitize_string(post_name).replace('.', '').strip()

                    try:
                        await DownloadSinglePostUseCase(
                            post_dto=post,
                            destination=self.destination / post_name,
                            download_context=self.context,
                        ).execute()
                    except ApplicationCancelledError:
                        self.context.progress_reporter.warn(
                            'Download cancelled by user. Bye!'
                        )
                    except ApplicationFailedDownloadError as e:
                        self.context.progress_reporter.error(
                            f'Failed to download post: {e.message}, RESOURCE: ({e.resource})'
                        )
                    else:
                        return

        self.context.progress_reporter.error(
            'Failed to find and download the specified post.'
        )
