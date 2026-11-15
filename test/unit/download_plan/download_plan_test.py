"""Dry-run observes complete saved records without changing the library."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.download_plan import (
    DownloadPlan,
    build_download_plan,
)
from boosty_downloader.application.post_preparation import PostPreparer
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from pathlib import Path

_DAY = datetime(2026, 1, 2, tzinfo=timezone.utc)
_EARLIER = datetime(2026, 1, 1, tzinfo=timezone.utc)
ALL_FILTERS = list(DownloadContentTypeFilter)


@pytest.fixture
def preparer(tmp_path: Path) -> PostPreparer:
    root = tmp_path / 'library'
    return PostPreparer(root, JsonPostStore(root), 'writer', BoostyOkVideoType.medium)


def _image(size: int = 10) -> dict[str, object]:
    return {
        'type': 'image',
        'id': 'i1',
        'url': 'https://images.example/i',
        'size': size,
    }


def _file(size: int = 20, *, complete: bool = True) -> dict[str, object]:
    return {
        'type': 'file',
        'id': 'f1',
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
    tags: list[dict[str, object]] | None = None,
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
            'tags': tags or [],
        }
    )


def _plan(
    posts: list[PostDTO],
    preparer: PostPreparer,
    filters: list[DownloadContentTypeFilter] = ALL_FILTERS,
    *,
    excluded_tags: tuple[str, ...] = (),
) -> DownloadPlan:
    return build_download_plan(
        posts, preparer=preparer, filters=filters, excluded_tags=excluded_tags, now=_DAY
    )


def _save(
    preparer: PostPreparer, post: PostDTO, downloaded: tuple[str, ...] = ()
) -> str:
    prepared = preparer.prepare(post, ALL_FILTERS, _EARLIER)
    record = prepared.reconciliation.record
    assert record is not None
    folder = preparer.library_root / prepared.folder
    folder.mkdir(parents=True)
    for media_id in downloaded:
        entry = record.media[media_id]
        entry.status = MediaStatus.downloaded
        entry.path = f'{media_id.replace(":", "_")}.bin'
        entry.size = prepared.live.media[media_id].expected_size or 5
        (folder / entry.path).write_bytes(b'x' * entry.size)
    record.sync.page_template = PAGE_TEMPLATE_VERSION
    preparer.store.save_post(prepared.folder, record)
    (folder / 'post.html').write_text('saved page')
    return prepared.folder


def test_new_post_counts_all_media_without_creating_library(preparer: PostPreparer):
    post = _post(data=[_image(), _file(), _audio(), _ok_video(), _ext_video()])
    plan = _plan([post], preparer)
    assert plan.new_posts == 1
    assert plan.media == MediaCounts(
        images=1, files=1, audio=1, boosty_videos=1, external_videos=1
    )
    assert plan.known_bytes == 60
    assert plan.unknown_size_videos == 2
    assert not preparer.library_root.exists()


def test_completed_record_is_unchanged_without_counting_sync_time(
    preparer: PostPreparer,
):
    post = _post(data=[_file()])
    folder = _save(preparer, post, ('file:f1',))
    paths = list((preparer.library_root / folder).iterdir())
    before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}
    plan = _plan([post], preparer)
    assert plan.unchanged_posts == 1
    assert plan.media == MediaCounts()
    assert before == {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths
    }


def test_author_text_update_needs_page_but_keeps_completed_media(
    preparer: PostPreparer,
):
    post = _post(updated_at=_EARLIER, data=[_file()])
    _save(preparer, post, ('file:f1',))
    plan = _plan([_post(data=[_file()])], preparer)
    assert plan.updated_posts == 1
    assert plan.media == MediaCounts()


def test_partial_record_counts_only_missing_piece_of_same_kind(preparer: PostPreparer):
    post = _post(data=[_file(), {**_file(41), 'id': 'f2'}])
    _save(preparer, post, ('file:f1',))
    plan = _plan([post], preparer)
    assert plan.updated_posts == 1
    assert plan.media == MediaCounts(files=1)
    assert plan.known_bytes == 41


def test_content_filters_keep_new_record_and_limit_media(preparer: PostPreparer):
    post = _post(data=[_file(), _image()])
    plan = _plan([post], preparer, [DownloadContentTypeFilter.files])
    assert plan.new_posts == 1
    assert plan.excluded_posts == 0
    assert plan.media == MediaCounts(files=1)


def test_unselected_media_does_not_make_existing_post_complete(preparer: PostPreparer):
    post = _post(data=[_file()])
    _save(preparer, post)
    plan = _plan([post], preparer, [DownloadContentTypeFilter.post_content])
    assert plan.unchanged_posts == 1
    assert plan.media == MediaCounts()


def test_text_only_and_unfinished_posts_still_need_new_records(preparer: PostPreparer):
    plan = _plan(
        [
            _post(),
            _post(
                'p2',
                data=[
                    _file(complete=False),
                    _audio(complete=False),
                    _ok_video(complete=False),
                ],
            ),
        ],
        preparer,
    )
    assert plan.new_posts == 2
    assert plan.media == MediaCounts()
    assert plan.known_bytes == 0


def test_locked_posts_are_not_planned(preparer: PostPreparer):
    plan = _plan([_post(has_access=False, data=[_file()])], preparer)
    assert plan.new_posts == 0
    assert plan.media == MediaCounts()
    assert not preparer.library_root.exists()


def test_excluded_tag_does_not_read_or_change_existing_record(preparer: PostPreparer):
    post = _post(data=[_file()], tags=[{'id': 1, 'title': 'Skip'}])
    folder = _save(preparer, post)
    record_path = preparer.library_root / folder / 'post.json'
    record_path.write_text('broken record')
    before = record_path.stat().st_mtime_ns
    plan = _plan([post], preparer, excluded_tags=('skip',))
    assert plan.excluded_posts == 1
    assert plan.new_posts == 0
    assert record_path.read_text() == 'broken record'
    assert record_path.stat().st_mtime_ns == before


def test_excluded_new_post_is_eligible_on_later_run(preparer: PostPreparer):
    post = _post(data=[_file()], tags=[{'id': 1, 'title': 'Skip'}])
    assert _plan([post], preparer, excluded_tags=('skip',)).excluded_posts == 1
    assert _plan([post], preparer).new_posts == 1
    assert not preparer.library_root.exists()


def test_missing_page_requires_update_without_media_download(preparer: PostPreparer):
    post = _post(data=[_file()])
    folder = _save(preparer, post, ('file:f1',))
    (preparer.library_root / folder / 'post.html').unlink()
    plan = _plan([post], preparer)
    assert plan.updated_posts == 1
    assert plan.media == MediaCounts()


def test_pending_media_uses_current_api_estimate(preparer: PostPreparer):
    _save(preparer, _post(data=[_file(20)]))
    plan = _plan([_post(data=[_file(45)])], preparer)
    assert plan.known_bytes == 45
