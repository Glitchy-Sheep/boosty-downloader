"""Shared full-listing walk for the metadata commands (check, dry-run)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.boosty_api.core.client import (
    MAX_POSTS_PER_PAGE,
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

if TYPE_CHECKING:
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
    from boosty_downloader.infrastructure.boosty_api.models.post.posts_request import (
        SkippedPost,
    )
    from boosty_downloader.infrastructure.loggers.base import RichLogger


@dataclass(frozen=True, slots=True)
class ListingWalk:
    """Everything one full listing walk produced."""

    posts: list[PostDTO]
    # Recap of posts the client could not parse and of unknown content,
    # None on a clean walk. The caller prints it after its own output.
    problems: str | None


async def walk_full_listing(
    boosty_api: BoostyAPIClient,
    author_name: str,
    logger: RichLogger,
) -> ListingWalk:
    """Collect every post of the author, warning inline about unparseable ones."""
    current_page = 0
    posts: list[PostDTO] = []

    all_skipped: list[SkippedPost] = []
    unknown_content: set[UnknownContent] = set()

    async for page in boosty_api.iterate_over_posts(
        author_name, posts_per_page=MAX_POSTS_PER_PAGE
    ):
        current_page += 1
        posts.extend(page.posts)

        all_skipped.extend(page.skipped_posts)
        for post in page.posts:
            unknown_content |= collect_unknown_content(post)

        for skipped in page.skipped_posts:
            logger.warning(format_skipped_post(skipped))

        logger.info(
            f'Processing page [bold]{current_page}[/bold]'
            ' | '
            f'Total posts so far: [bold]{len(posts)}[/bold]'
        )

    return ListingWalk(
        posts=posts,
        problems=format_run_summary(all_skipped, unknown_content),
    )
