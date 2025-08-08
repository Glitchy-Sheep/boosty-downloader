"""Use case for reporting the total number of posts and their accessibility for a given Boosty author."""

from boosty_downloader.src.infrastructure.boosty_api.core.client import (
    BoostyAPIClient,
)
from boosty_downloader.src.infrastructure.loggers.logger_instances import RichLogger


class ReportTotalPostsCountUseCase:
    """
    Reports the total number of posts and their accessibility for a given Boosty author.

    This use case iterates over all posts for the specified author, counts accessible and inaccessible posts,
    and reports the results using the provided ProgressReporter.
    """

    def __init__(
        self,
        author_name: str,
        logger: RichLogger,
        boosty_api: BoostyAPIClient,
    ) -> None:
        self.author_name = author_name
        self.logger = logger
        self.boosty_api = boosty_api

    async def execute(self) -> None:
        current_page = 0
        total_posts = 0

        accessible_posts_count = 0
        inaccessible_posts_count = 0
        inaccessible_posts_names: list[str] = []

        async for page in self.boosty_api.iterate_over_posts(
            self.author_name, posts_per_page=100
        ):
            current_page += 1
            total_posts += len(page.posts)

            self.logger.info(
                f'Processing page [bold]{current_page}[/bold]'
                ' | '
                f'Total posts so far: [bold]{total_posts}[/bold]'
            )

            for post in page.posts:
                if post.has_access:
                    accessible_posts_count += 1
                else:
                    inaccessible_posts_count += 1
                    inaccessible_posts_names.append('     - ' + post.title + '\n')

        inaccessible_titles_str = ''.join(inaccessible_posts_names)

        self.logger.success(
            f'Total posts: [bold]{total_posts}[/bold]\n'
            f'Accessible posts: [bold]{accessible_posts_count}[/bold]\n'
            f'Inaccessible posts: [bold]{inaccessible_posts_count}[/bold] (need higher tier subscription) see their titles:\n'
            '\n'
            f'[bold]{inaccessible_titles_str}[/bold]'
        )
