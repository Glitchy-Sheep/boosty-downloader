"""Auxiliary post images are durable, filter-independent and visible to planning."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from e2e.download_flow_test import (
    AUTHOR,
    POST_DIR_NAME,
    _build_app,
    _dry_run,
    _QuietReporter,
    _run_download,
)
from support.synthetic_post import (
    IMAGE_ID,
    IMAGES_HOST,
    POST_ID,
    VIDEO_ID,
    image_chunk,
    ok_video_chunk,
    synthetic_post,
    text_chunk,
)

from boosty_downloader.application import post_retry as post_retry_module
from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.post_download_state import PostDownloadState
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post_cover import select_locked_cover, select_post_cover
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.library.author_records import read_locked_posts
from boosty_downloader.infrastructure.library.media_snapshot import read_media_snapshot
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path
    from typing import Any

    from boosty_downloader.domain.library import LocatedPost

VIDEO_MEDIA_ID = f'boosty_video:{VIDEO_ID}'
SECOND_IMAGE_ID = '10000000-0000-4000-8000-000000000202'


@dataclass
class _AuxiliaryImages:
    requests: list[str] = field(default_factory=list[str])
    failures: dict[str, int] = field(default_factory=dict[str, int])

    @web.middleware
    async def handle(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if request.path.startswith(('/preview/', '/teaser/')):
            self.requests.append(request.path)
            if request.path in self.failures:
                return web.Response(status=self.failures[request.path])
            return web.Response(body=b'auxiliary image bytes', content_type='image/png')
        return await handler(request)

    def app(self, primary: list[str], payload: dict[str, Any]) -> web.Application:
        app = _build_app(primary, payload=payload)
        app.middlewares.append(self.handle)
        return app


@dataclass(frozen=True, slots=True)
class _FileState:
    content: bytes | None
    modified_ns: int


def _snapshot(root: Path) -> dict[str, _FileState]:
    return {
        path.relative_to(root).as_posix(): _FileState(
            path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns
        )
        for path in [root, *root.rglob('*')]
    }


def _located(root: Path) -> LocatedPost:
    located = JsonPostStore(root).find_post(AUTHOR, POST_ID)
    assert located is not None
    assert located.record is not None
    return located


def _video_post(*, ready: bool = True) -> dict[str, Any]:
    payload = synthetic_post()
    video = ok_video_chunk()
    if not ready:
        video.update(complete=False, playerUrls=[])
    payload['data'] = [text_chunk('Video description'), video]
    return payload


@pytest.mark.parametrize('ready', [False, True], ids=['unfinished', 'ready'])
async def test_video_preview_downloads_without_video_and_is_reused(
    tmp_path: Path,
    *,
    ready: bool,
) -> None:
    primary: list[str] = []
    images = _AuxiliaryImages()
    filters = [DownloadContentTypeFilter.post_content]
    async with TestServer(images.app(primary, _video_post(ready=ready))) as server:
        stats = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )
        located = _located(tmp_path)
        assert located.record is not None
        media = located.record.media[VIDEO_MEDIA_ID]
        assert media.path is None
        assert media.preview_path is not None
        preview = tmp_path / located.folder / media.preview_path
        assert preview.read_bytes() == b'auxiliary image bytes'
        assert media.preview_path.startswith('previews/')
        assert (
            select_post_cover(
                located.record, read_media_snapshot(tmp_path, located.folder)
            )
            == media.preview_path
        )
        before = _snapshot(tmp_path)
        plan = await _dry_run(tmp_path, server.make_url('/'), filters=filters)
        assert plan.plan.unchanged_posts == 1
        assert _snapshot(tmp_path) == before
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )

    assert images.requests == ['/preview/full']
    assert primary == []
    assert stats.media == MediaCounts()
    assert stats.downloaded_bytes == 0
    assert stats.media_deleted == 0


async def test_missing_preview_is_planned_read_only_and_restored_without_video(
    tmp_path: Path,
) -> None:
    primary: list[str] = []
    images = _AuxiliaryImages()
    filters = [DownloadContentTypeFilter.post_content]
    async with TestServer(images.app(primary, _video_post())) as server:
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )
        located = _located(tmp_path)
        assert located.record is not None
        path = located.record.media[VIDEO_MEDIA_ID].preview_path
        assert path is not None
        (tmp_path / located.folder / path).unlink()
        images.requests.clear()
        before = _snapshot(tmp_path)
        plan = await _dry_run(tmp_path, server.make_url('/'), filters=filters)
        assert plan.plan.updated_posts == 1
        assert plan.plan.media == MediaCounts()
        assert images.requests == []
        assert _snapshot(tmp_path) == before
        stats = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )

    current = _located(tmp_path)
    assert current.record is not None
    path = current.record.media[VIDEO_MEDIA_ID].preview_path
    assert path is not None
    assert (tmp_path / current.folder / path).is_file()
    assert images.requests == ['/preview/full']
    assert primary == []
    assert stats.media_deleted == 0


@pytest.mark.parametrize(
    'content_type',
    [DownloadContentTypeFilter.post_content, DownloadContentTypeFilter.boosty_videos],
)
async def test_failed_preview_is_warned_and_retried_on_the_next_run(
    tmp_path: Path,
    content_type: DownloadContentTypeFilter,
) -> None:
    primary: list[str] = []
    images = _AuxiliaryImages(failures={'/preview/full': 404})
    filters = [content_type]
    async with TestServer(images.app(primary, _video_post())) as server:
        reporter = _QuietReporter()
        first = await _run_download(
            tmp_path, server.make_url('/'), reporter, filters=filters
        )
        located = _located(tmp_path)
        assert located.record is not None
        assert located.record.media[VIDEO_MEDIA_ID].preview_path is None
        page = (tmp_path / located.folder / 'post.html').read_text(encoding='utf-8')
        assert 'poster=' not in page
        assert first.posts_failed == 0
        assert reporter.warnings
        images.failures.clear()
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )

    located = _located(tmp_path)
    assert located.record is not None
    media = located.record.media[VIDEO_MEDIA_ID]
    assert media.preview_path is not None
    page = (tmp_path / located.folder / 'post.html').read_text(encoding='utf-8')
    if content_type is DownloadContentTypeFilter.boosty_videos:
        assert media.status is MediaStatus.downloaded
        assert f'poster="{quote(media.preview_path, safe="/")}"' in page
        assert 'preload="metadata"' in page
        assert len(primary) == 1
    else:
        assert media.status is MediaStatus.pending
        assert '<video' not in page
        assert primary == []
    assert images.requests == ['/preview/full', '/preview/full']


@pytest.mark.parametrize('excluded', [False, True])
async def test_locked_teaser_is_separate_from_post_content_and_respects_tags(
    tmp_path: Path,
    *,
    excluded: bool,
) -> None:
    payload = synthetic_post()
    payload.update(hasAccess=False, data=[])
    primary: list[str] = []
    images = _AuxiliaryImages()
    async with TestServer(images.app(primary, payload)) as server:
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            excluded_tags=('fixture',) if excluded else (),
        )
    locked = read_locked_posts(tmp_path, AUTHOR)[POST_ID]
    if excluded:
        assert locked.teaser_path is None
        assert images.requests == []
    else:
        assert locked.teaser_path is not None
        assert locked.teaser_path == f'.boosty-downloader/teasers/{POST_ID}.png'
        assert (
            tmp_path / AUTHOR / locked.teaser_path
        ).read_bytes() == b'auxiliary image bytes'
        assert (
            select_locked_cover(locked, read_media_snapshot(tmp_path, AUTHOR))
            == locked.teaser_path
        )
        assert len(images.requests) == 1
    assert not (tmp_path / AUTHOR / POST_DIR_NAME).exists()
    assert primary == []
    assert stats.media == MediaCounts()


async def test_existing_teaser_survives_metadata_changes_and_missing_remote_url(
    tmp_path: Path,
) -> None:
    payload = synthetic_post()
    payload.update(hasAccess=False, data=[])
    images = _AuxiliaryImages()
    async with TestServer(images.app([], payload)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    first = read_locked_posts(tmp_path, AUTHOR)[POST_ID]
    assert first.teaser_path is not None
    file = tmp_path / AUTHOR / first.teaser_path
    original = _FileState(file.read_bytes(), file.stat().st_mtime_ns)
    images.requests.clear()
    payload.update(title='Updated locked overview', teaser=[])
    async with TestServer(images.app([], payload)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    current = read_locked_posts(tmp_path, AUTHOR)[POST_ID]
    assert current.post.title == 'Updated locked overview'
    assert current.teaser_path == first.teaser_path
    assert _FileState(file.read_bytes(), file.stat().st_mtime_ns) == original
    assert images.requests == []


async def test_excluded_accessible_post_never_requests_its_preview(
    tmp_path: Path,
) -> None:
    primary: list[str] = []
    images = _AuxiliaryImages()
    async with TestServer(images.app(primary, _video_post())) as server:
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), excluded_tags=('fixture',)
        )
    assert primary == []
    assert images.requests == []
    assert not (tmp_path / AUTHOR / POST_DIR_NAME).exists()


async def test_cover_moves_to_the_next_current_image_after_author_removal(
    tmp_path: Path,
) -> None:
    payload = _video_post()
    payload['data'] = [
        image_chunk(),
        {
            **image_chunk(),
            'id': SECOND_IMAGE_ID,
            'url': f'{IMAGES_HOST}/image/second',
        },
        ok_video_chunk(),
    ]
    images = _AuxiliaryImages()
    async with TestServer(images.app([], payload)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    first = _located(tmp_path)
    assert first.record is not None
    first_cover = select_post_cover(
        first.record, read_media_snapshot(tmp_path, first.folder)
    )
    assert first_cover == first.record.media[f'image:{IMAGE_ID}'].path
    assert first_cover is not None
    payload['data'] = [
        chunk for chunk in payload['data'] if chunk.get('id') != IMAGE_ID
    ]
    primary: list[str] = []
    images.requests.clear()
    async with TestServer(images.app(primary, payload)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    current = _located(tmp_path)
    assert current.record is not None
    cover = select_post_cover(
        current.record, read_media_snapshot(tmp_path, current.folder)
    )
    assert cover == current.record.media[f'image:{SECOND_IMAGE_ID}'].path
    assert (tmp_path / first.folder / first_cover).is_file()
    assert primary == []
    assert images.requests == []


async def test_preview_record_failure_is_not_hidden_as_an_optional_image_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    folder = tmp_path / AUTHOR / POST_DIR_NAME
    foreign = folder / 'previews' / f'{VIDEO_ID}.png'
    foreign.parent.mkdir(parents=True)
    foreign.write_bytes(b'keep this occupied file')
    original = _FileState(foreign.read_bytes(), foreign.stat().st_mtime_ns)
    complete = PostDownloadState.complete_preview
    published: list[Path] = []

    def fail_save(self: PostDownloadState, media_id: str, path: str) -> None:
        assert media_id == VIDEO_MEDIA_ID
        output = tmp_path / self.folder / path
        assert output.is_file()
        published.append(output)
        message = 'Preview record cannot be saved'
        raise OSError(message)

    monkeypatch.setattr(PostDownloadState, 'complete_preview', fail_save)
    images = _AuxiliaryImages()
    filters = [DownloadContentTypeFilter.post_content]
    async with TestServer(images.app([], _video_post())) as server:
        reporter = _QuietReporter()
        stats = await _run_download(
            tmp_path, server.make_url('/'), reporter, filters=filters
        )
        assert stats.posts_failed == 1
        assert any(
            'Preview record cannot be saved' in message for message in reporter.errors
        )
        assert len(published) == 1
        assert published[0].read_bytes() == b'auxiliary image bytes'
        assert published[0] != foreign
        located = _located(tmp_path)
        assert located.record is not None
        assert located.record.media[VIDEO_MEDIA_ID].preview_path is None
        monkeypatch.setattr(PostDownloadState, 'complete_preview', complete)
        stats = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )

    assert stats.posts_failed == 0
    assert _FileState(foreign.read_bytes(), foreign.stat().st_mtime_ns) == original
    assert published[0].read_bytes() == b'auxiliary image bytes'
    current = _located(tmp_path)
    assert current.record is not None
    assert current.record.media[VIDEO_MEDIA_ID].preview_path is not None


async def test_failed_missing_teaser_keeps_the_observation_and_old_path(
    tmp_path: Path,
) -> None:
    payload = synthetic_post()
    payload.update(hasAccess=False, data=[])
    images = _AuxiliaryImages()
    async with TestServer(images.app([], payload)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    first = read_locked_posts(tmp_path, AUTHOR)[POST_ID]
    assert first.teaser_path is not None
    teaser_file = tmp_path / AUTHOR / first.teaser_path
    teaser_file.unlink()
    teaser_url_path = images.requests[-1]
    images.failures[teaser_url_path] = 404
    payload['title'] = 'New overview despite missing teaser'
    async with TestServer(images.app([], payload)) as server:
        reporter = _QuietReporter()
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)
    current = read_locked_posts(tmp_path, AUTHOR)[POST_ID]
    assert current.post.title == payload['title']
    assert current.teaser_path == first.teaser_path
    assert not teaser_file.exists()
    assert stats.posts_failed == 0
    assert stats.posts_locked == 1
    assert any('teaser' in message.lower() for message in reporter.warnings)
    assert not (tmp_path / AUTHOR / POST_DIR_NAME).exists()


@pytest.mark.parametrize(
    'first_status',
    [HTTPStatus.NOT_FOUND, HTTPStatus.FORBIDDEN],
    ids=['retry', 'refresh'],
)
async def test_finished_preview_is_not_downloaded_again_by_post_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_status: HTTPStatus,
) -> None:
    async def no_sleep(_delay: float) -> None:
        return

    monkeypatch.setattr(post_retry_module.asyncio, 'sleep', no_sleep)
    primary: list[str] = []
    images = _AuxiliaryImages()
    app = _build_app(primary, fail_first_file=True, first_file_status=first_status)
    app.middlewares.append(images.handle)
    async with TestServer(app) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    located = _located(tmp_path)
    assert located.record is not None
    assert located.record.media[VIDEO_MEDIA_ID].preview_path is not None
    preview_path = located.record.media[VIDEO_MEDIA_ID].preview_path
    assert preview_path is not None
    page = (tmp_path / located.folder / 'post.html').read_text(encoding='utf-8')
    assert f'poster="{quote(preview_path, safe="/")}"' in page
    assert 'preload="metadata"' in page
    assert images.requests == ['/preview/full']
    assert stats.posts_failed == 0
    assert stats.posts_downloaded == 1
    assert stats.media == MediaCounts(images=1, files=1, audio=1, boosty_videos=1)


async def test_saved_preview_is_kept_when_the_remote_url_disappears(
    tmp_path: Path,
) -> None:
    payload = _video_post()
    images = _AuxiliaryImages()
    filters = [DownloadContentTypeFilter.post_content]
    async with TestServer(images.app([], payload)) as server:
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )
    first = _located(tmp_path)
    assert first.record is not None
    path = first.record.media[VIDEO_MEDIA_ID].preview_path
    assert path is not None
    preview = tmp_path / first.folder / path
    original = _FileState(preview.read_bytes(), preview.stat().st_mtime_ns)
    payload['data'][-1]['preview'] = ''
    images.requests.clear()
    async with TestServer(images.app([], payload)) as server:
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )
    current = _located(tmp_path)
    assert current.record is not None
    assert current.record.media[VIDEO_MEDIA_ID].preview_path == path
    assert _FileState(preview.read_bytes(), preview.stat().st_mtime_ns) == original
    assert images.requests == []


@pytest.mark.parametrize(
    'primary_status',
    [MediaStatus.pending, MediaStatus.downloaded],
    ids=['pending', 'deleted-on-disk'],
)
async def test_preview_cannot_take_a_retained_primary_media_path(
    tmp_path: Path,
    primary_status: MediaStatus,
) -> None:
    images = _AuxiliaryImages()
    async with TestServer(images.app([], synthetic_post())) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    located = _located(tmp_path)
    assert located.record is not None
    record = deepcopy(located.record)
    preview_path = record.media[VIDEO_MEDIA_ID].preview_path
    assert preview_path is not None
    (tmp_path / located.folder / preview_path).unlink()
    record.media[VIDEO_MEDIA_ID].preview_path = None
    primary_id = f'image:{IMAGE_ID}'
    primary_media = record.media[primary_id]
    assert primary_media.path is not None
    (tmp_path / located.folder / primary_media.path).unlink()
    primary_media.path = preview_path
    primary_media.status = primary_status
    JsonPostStore(tmp_path).save_post(located.folder, record)
    primary_requests: list[str] = []
    images.requests.clear()
    filters = [DownloadContentTypeFilter.post_content]
    async with TestServer(images.app(primary_requests, synthetic_post())) as server:
        first = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )
        second = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )

    current = _located(tmp_path)
    assert current.record is not None
    new_preview = current.record.media[VIDEO_MEDIA_ID].preview_path
    assert new_preview is not None
    assert new_preview != preview_path
    assert (
        tmp_path / current.folder / new_preview
    ).read_bytes() == b'auxiliary image bytes'
    assert current.record.media[primary_id].path == preview_path
    assert images.requests == ['/preview/full']
    assert first.posts_failed == second.posts_failed == 0
    if primary_status is MediaStatus.pending:
        assert primary_requests == [f'/image/{IMAGE_ID}']
        assert (tmp_path / current.folder / preview_path).read_bytes() == b'png bytes'
        assert current.record.media[primary_id].status is MediaStatus.downloaded
    else:
        assert primary_requests == []
        assert not (tmp_path / current.folder / preview_path).exists()
        assert current.record.media[primary_id].status is MediaStatus.deleted
        assert first.media_deleted == second.media_deleted == 1
