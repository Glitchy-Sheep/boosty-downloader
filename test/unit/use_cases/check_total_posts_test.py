"""Regression test: skipped posts must reach the user as warnings."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from boosty_downloader.src.application.use_cases.check_total_posts import (
    ReportTotalPostsCountUseCase,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.extra import Extra
from boosty_downloader.src.infrastructure.boosty_api.models.post.posts_request import (
    PostsResponse,
    SkippedPost,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from boosty_downloader.src.infrastructure.boosty_api.core.client import (
        BoostyAPIClient,
    )
    from boosty_downloader.src.infrastructure.loggers.logger_instances import RichLogger


class _FakeLogger:
    """Collects log lines instead of printing them."""

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.other: list[str] = []

    def warning(self, msg: str, **kwargs: object) -> None:
        del kwargs
        self.warnings.append(msg)

    def info(self, msg: str, **kwargs: object) -> None:
        del kwargs
        self.other.append(msg)

    def success(self, msg: str, **kwargs: object) -> None:
        del kwargs
        self.other.append(msg)


class _FakeApi:
    """One page with one skipped post, then stop."""

    def __init__(self, page: PostsResponse) -> None:
        self._page = page

    async def iterate_over_posts(
        self, *args: object, **kwargs: object
    ) -> AsyncGenerator[PostsResponse, None]:
        del args, kwargs
        yield self._page


@pytest.mark.asyncio
async def test_skipped_post_becomes_a_warning():
    page = PostsResponse(
        posts=[],
        extra=Extra(offset='', is_last=True),
        skipped_posts=[
            SkippedPost(
                post_id='b1',
                title='broken post',
                errors=[],
            )
        ],
    )
    logger = _FakeLogger()
    use_case = ReportTotalPostsCountUseCase(
        author_name='any_author',
        logger=cast('RichLogger', logger),
        boosty_api=cast('BoostyAPIClient', _FakeApi(page)),
    )

    await use_case.execute()

    assert len(logger.warnings) == 1
    assert 'broken post' in logger.warnings[0]
    assert 'b1' in logger.warnings[0]
