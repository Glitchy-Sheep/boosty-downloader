"""Implements the use case for downloading all posts from a Boosty author, applying filters and caching as needed."""

from pathlib import Path

from aiohttp_retry import RetryClient

from boosty_downloader.src.application.download_manager.download_manager import (
    sanitize_string,
)
from boosty_downloader.src.application.filtering import (
    DownloadContentTypeFilter,
)
from boosty_downloader.src.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.src.infrastructure.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.src.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.src.infrastructure.loggers.logger_instances import (
    downloader_logger,
)
from boosty_downloader.src.infrastructure.post_caching.post_cache import SQLitePostCache
from boosty_downloader.src.interfaces.console_progress_reporter import ProgressReporter


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
        downloader_session: RetryClient,
        external_videos_downloader: ExternalVideosDownloader,
        post_cache: SQLitePostCache,
        filters: list[DownloadContentTypeFilter],
        progress_reporter: ProgressReporter,
    ) -> None:
        self.author_name = author_name

        self.boosty_api = boosty_api
        self.destination = destination
        self.downloader_session = downloader_session
        self.external_videos_downloader = external_videos_downloader
        self.post_cache = post_cache
        self.filters = filters
        self.progress_reporter = progress_reporter

    async def execute(self) -> None:
        posts_iterator = self.boosty_api.iterate_over_posts(
            author_name=self.author_name
        )

        current_page = 0

        async for page in posts_iterator:
            count = len(page.posts)
            current_page += 1

            page_task_id = self.progress_reporter.create_task(
                f'Got new posts: [{count}]',
                total=count,
                indent_level=0,  # Each page prints without indentation
            )

            for post_dto in page.posts:
                if not post_dto.has_access:
                    downloader_logger.warning(
                        f'Skip post (no access to content): {post_dto.title}'
                    )
                    continue

                # For empty titles use post ID as a fallback (first 8 chars)
                if len(post_dto.title) == 0:
                    post_dto.title = f'Not title (id_{post_dto.id[:8]})'

                post_dto.title = (
                    sanitize_string(post_dto.title).replace('.', '').strip()
                )

                full_post_title = f'{post_dto.created_at.date()} - {post_dto.title}'

                single_post_use_case = DownloadSinglePostUseCase(
                    destination=self.destination / full_post_title,
                    post_dto=post_dto,
                    downloader_session=self.downloader_session,
                    external_videos_downloader=self.external_videos_downloader,
                    post_cache=self.post_cache,
                    filters=self.filters,
                    progress_reporter=self.progress_reporter,
                )

                self.progress_reporter.update_task(
                    page_task_id,
                    advance=1,
                    description=f'Processing page [bold]{current_page}[/bold]',
                )
                await single_post_use_case.execute()

            self.progress_reporter.complete_task(page_task_id)
            self.progress_reporter.success(f'--- Finished page {current_page} ---')
