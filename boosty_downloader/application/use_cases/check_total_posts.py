"""Use case: list an author's posts and build the blog overview."""

from dataclasses import dataclass

from boosty_downloader.application.blog_overview import BlogOverview, summarize_posts
from boosty_downloader.application.use_cases.listing_walk import walk_full_listing
from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.infrastructure.loggers.base import RichLogger


@dataclass(frozen=True, slots=True)
class CheckReport:
    """What the listing walk produced."""

    overview: BlogOverview
    # Recap of posts the client could not parse and of unknown content,
    # None on a clean walk. The caller prints it after the overview.
    problems: str | None


class ReportTotalPostsCountUseCase:
    """
    Walks all posts of a Boosty author and builds the blog overview.

    Warns about posts the client could not parse along the way; the caller
    renders the returned report.
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

    async def execute(self) -> CheckReport:
        walk = await walk_full_listing(self.boosty_api, self.author_name, self.logger)
        return CheckReport(
            overview=summarize_posts(walk.posts),
            problems=walk.problems,
        )
