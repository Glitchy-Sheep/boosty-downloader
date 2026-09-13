"""Use case: preview what a download run would fetch, without downloading anything."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from boosty_downloader.application.blog_overview import BlogOverview, summarize_posts
from boosty_downloader.application.download_plan import (
    DownloadPlan,
    build_download_plan,
)
from boosty_downloader.application.use_cases.listing_walk import walk_full_listing

if TYPE_CHECKING:
    from collections.abc import Sequence

    from boosty_downloader.application.ports import PostCache
    from boosty_downloader.domain.content_types import DownloadContentTypeFilter
    from boosty_downloader.infrastructure.boosty_api.core.client import (
        BoostyAPIClient,
    )
    from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
        BoostyOkVideoType,
    )
    from boosty_downloader.infrastructure.loggers.base import RichLogger


@dataclass(frozen=True, slots=True)
class DryRunReport:
    """Blog overview plus the download plan for the current cache and filters."""

    overview: BlogOverview
    plan: DownloadPlan
    # Recap of posts the client could not parse, None on a clean walk.
    problems: str | None


class PlanDownloadUseCase:
    """
    Walks the listing and answers "what would a download run do right now".

    Reads the same cache and applies the same filters as the real run;
    downloads nothing and changes nothing.
    """

    def __init__(  # noqa: PLR0913 - the dry-run needs the same knobs as the real run
        self,
        *,
        author_name: str,
        boosty_api: BoostyAPIClient,
        logger: RichLogger,
        post_cache: PostCache,
        filters: Sequence[DownloadContentTypeFilter],
        preferred_video_quality: BoostyOkVideoType,
    ) -> None:
        self.author_name = author_name
        self.boosty_api = boosty_api
        self.logger = logger
        self.post_cache = post_cache
        self.filters = filters
        self.preferred_video_quality = preferred_video_quality

    async def execute(self) -> DryRunReport:
        walk = await walk_full_listing(self.boosty_api, self.author_name, self.logger)
        return DryRunReport(
            overview=summarize_posts(self.author_name, walk.posts),
            plan=build_download_plan(
                walk.posts,
                post_cache=self.post_cache,
                filters=self.filters,
                preferred_video_quality=self.preferred_video_quality,
            ),
            problems=walk.problems,
        )
