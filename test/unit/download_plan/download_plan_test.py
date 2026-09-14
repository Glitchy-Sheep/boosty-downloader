"""
Tests for the download plan against a real SQLite cache.

The plan must repeat the downloader's own decisions: same mapping,
same cache answers, same filters - otherwise --dry-run lies.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.download_plan import (
    DownloadPlan,
    build_download_plan,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)
from boosty_downloader.infrastructure.loggers.base import RichLogger
from boosty_downloader.infrastructure.post_caching.post_cache import SQLitePostCache

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

_DAY = datetime(2026, 1, 2, tzinfo=timezone.utc)
_EARLIER = datetime(2026, 1, 1, tzinfo=timezone.utc)

ALL_FILTERS = list(DownloadContentTypeFilter)


@pytest.fixture
def cache(tmp_path: Path) -> Iterator[SQLitePostCache]:
    with SQLitePostCache(tmp_path, RichLogger('plan-test')) as post_cache:
        yield post_cache


def _image(size: int = 10) -> dict[str, object]:
    return {'type': 'image', 'url': 'https://images.example/i', 'size': size}


def _file(size: int = 20, *, complete: bool = True) -> dict[str, object]:
    return {
        'type': 'file',
        'url': 'https://cdn.example/f',
        'title': 'a.zip',
        'size': size,
        'complete': complete,
    }


def _audio(size: int = 30, *, complete: bool = True) -> dict[str, object]:
    return {
        'type': 'audio_file',
        'id': 'a1',
        'url': 'https://cdn.example/a',
        'title': 'song.mp3',
        'size': size,
        'complete': complete,
        'timeCode': 0,
        'showViewsCounter': False,
        'uploadStatus': None,
        'viewsCounter': 0,
    }


def _ok_video(*, complete: bool = True) -> dict[str, object]:
    return {
        'type': 'ok_video',
        'id': 'v1',
        'title': 'clip',
        'failoverHost': 'x',
        'duration': 1,
        'complete': complete,
        'playerUrls': [{'type': 'medium', 'url': 'https://video.example/v.mp4'}],
    }


def _ext_video() -> dict[str, object]:
    return {'type': 'video', 'url': 'https://video.example/watch'}


def _post(
    post_id: str = 'p1',
    *,
    updated_at: datetime = _DAY,
    data: list[dict[str, object]] | None = None,
    has_access: bool = True,
) -> PostDTO:
    return PostDTO.model_validate(
        {
            'id': post_id,
            'title': f'post {post_id}',
            'createdAt': _DAY,
            'updatedAt': updated_at,
            'hasAccess': has_access,
            'signedQuery': '?sq',
            'data': data or [],
        }
    )


def _plan(
    posts: list[PostDTO],
    cache: SQLitePostCache,
    filters: list[DownloadContentTypeFilter] = ALL_FILTERS,
) -> DownloadPlan:
    return build_download_plan(
        posts,
        post_cache=cache,
        filters=filters,
        preferred_video_quality=BoostyOkVideoType.medium,
    )


def test_new_post_counts_every_media_kind_and_known_bytes(cache: SQLitePostCache):
    post = _post(data=[_image(10), _file(20), _audio(30), _ok_video(), _ext_video()])

    plan = _plan([post], cache)

    assert plan.new_posts == 1
    assert plan.media == MediaCounts(
        images=1, files=1, boosty_videos=1, external_videos=1, audio=1
    )
    # Sizes the API reports; both videos land in the unknown-size bucket.
    assert plan.known_bytes == 60
    assert plan.unknown_size_videos == 2


def test_fully_cached_post_is_complete_and_adds_nothing(cache: SQLitePostCache):
    post = _post(data=[_image(), _file()])
    cache.cache_post(post.id, post.updated_at, ALL_FILTERS)

    plan = _plan([post], cache)

    assert plan.complete_posts == 1
    assert plan.new_posts == 0
    assert plan.media == MediaCounts()
    assert plan.known_bytes == 0


def test_author_update_makes_the_post_outdated_and_recounts_media(
    cache: SQLitePostCache,
):
    """The cache promise: an updated post re-downloads fully."""
    post = _post(updated_at=_DAY, data=[_image(10), _file(20)])
    cache.cache_post(post.id, _EARLIER, ALL_FILTERS)

    plan = _plan([post], cache)

    assert plan.outdated_posts == 1
    assert plan.new_posts == 0
    assert plan.media == MediaCounts(images=1, files=1)
    assert plan.known_bytes == 30


def test_partially_cached_post_counts_only_the_missing_parts(cache: SQLitePostCache):
    """Everything but audio is cached: only the audio may be fetched."""
    post = _post(data=[_image(10), _audio(30)])
    cached_parts = [
        part for part in ALL_FILTERS if part is not DownloadContentTypeFilter.audio
    ]
    cache.cache_post(post.id, post.updated_at, cached_parts)

    plan = _plan([post], cache)

    assert plan.outdated_posts == 1
    assert plan.media == MediaCounts(audio=1)
    assert plan.known_bytes == 30


def test_filters_narrow_the_plan_like_the_real_run(cache: SQLitePostCache):
    with_file = _post('has-file', data=[_file(20), _image(10)])
    without_file = _post('no-file', data=[_image(10)])

    plan = _plan(
        [with_file, without_file], cache, filters=[DownloadContentTypeFilter.files]
    )

    assert plan.new_posts == 1
    assert plan.filtered_out_posts == 1
    # The image is post_content and post_content is not requested.
    assert plan.media == MediaCounts(files=1)
    assert plan.known_bytes == 20


def test_unfinished_uploads_are_not_promised(cache: SQLitePostCache):
    """The downloader skips complete=False media; the plan must not sell them."""
    post = _post(
        data=[_ok_video(complete=False), _audio(complete=False), _file(complete=False)]
    )

    plan = _plan([post], cache)

    # Nothing mappable is left, so the run would skip this post entirely.
    assert plan.filtered_out_posts == 1
    assert plan.new_posts == 0
    assert plan.media == MediaCounts()
    assert plan.known_bytes == 0
    assert plan.unknown_size_videos == 0


def test_locked_posts_are_not_planned(cache: SQLitePostCache):
    post = _post(has_access=False, data=[_image(10)])

    plan = _plan([post], cache)

    assert plan.new_posts == 0
    assert plan.media == MediaCounts()
