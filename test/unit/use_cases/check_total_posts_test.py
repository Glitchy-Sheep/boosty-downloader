"""Regression test: skipped posts must reach the user as warnings."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

import pytest

from boosty_downloader.src.application.use_cases.check_total_posts import (
    ReportTotalPostsCountUseCase,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.extra import Extra
from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataUnknownDTO,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.posts_request import (
    PostsResponse,
    SkippedPost,
)
from boosty_downloader.src.infrastructure.boosty_api.utils.validation_errors import (
    GITHUB_ISSUES_URL,
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


def _make_post_with_unknown_chunk() -> PostDTO:
    return PostDTO(
        id='p1',
        title='post with novelty',
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        has_access=True,
        signed_query='',
        data=[BoostyPostDataUnknownDTO(type='novel_thing')],
    )


@pytest.mark.asyncio
async def test_skipped_post_warns_inline_and_run_summary_reports_everything():
    page = PostsResponse(
        posts=[_make_post_with_unknown_chunk()],
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

    inline, summary = logger.warnings
    assert 'broken post' in inline
    assert 'b1' in inline
    assert "data[0].type = 'novel_thing'" in summary
    assert 'broken post' in summary
    assert GITHUB_ISSUES_URL in summary
