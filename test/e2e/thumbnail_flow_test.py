"""Thumbnail transfers augment saved content without changing primary outcomes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pytest
from aiohttp.test_utils import TestServer
from e2e.download_flow_test import (
    AUTHOR,
    POST_DIR_NAME,
    THUMBNAIL_PNG,
    _build_app,  # pyright: ignore[reportPrivateUsage]
    _dry_run,  # pyright: ignore[reportPrivateUsage]
    _QuietReporter,  # pyright: ignore[reportPrivateUsage]
    _run_download,  # pyright: ignore[reportPrivateUsage]
)
from e2e.library_compatibility_flow_test import (
    _local_network,  # pyright: ignore[reportPrivateUsage]
    _snapshot,  # pyright: ignore[reportPrivateUsage]
    _write_config,  # pyright: ignore[reportPrivateUsage]
)
from sqlalchemy import select
from support.synthetic_post import (
    FILE_ID,
    IMAGE_ID,
    POST_ID,
    TEASER_ID,
    VIDEO_ID,
    image_chunk,
    ok_video_chunk,
    synthetic_post,
)
from typer.testing import CliRunner

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.media_thumbnails import media_thumbnail_path
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost
from boosty_downloader.infrastructure.library.author_records import read_locked_posts
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from aiohttp import web

    from boosty_downloader.domain.stored_post import StoredPost

IMAGE_MEDIA_ID = f'image:{IMAGE_ID}'
VIDEO_MEDIA_ID = f'boosty_video:{VIDEO_ID}'


@dataclass
class _Requests:
    primary: list[str] = field(default_factory=list[str])
    thumbnails: list[str] = field(default_factory=list[str])
    auxiliary: list[str] = field(default_factory=list[str])

    def app(
        self,
        payload: dict[str, Any] | None = None,
        *,
        thumbnail_status: int = 200,
        fail_first_file: bool = False,
    ) -> web.Application:
        return _build_app(
            self.primary,
            payload=payload,
            served_thumbnails=self.thumbnails,
            served_auxiliary=self.auxiliary,
            thumbnail_status=thumbnail_status,
            fail_first_file=fail_first_file,
        )

    def clear(self) -> None:
        self.primary.clear()
        self.thumbnails.clear()
        self.auxiliary.clear()

    def assert_empty(self) -> None:
        assert self.primary == []
        assert self.thumbnails == []
        assert self.auxiliary == []


@pytest.fixture
def requests() -> _Requests:
    return _Requests()


def _record(root: Path) -> StoredPost:
    located = JsonPostStore(root).find_post(AUTHOR, POST_ID)
    assert located is not None
    assert located.record is not None
    return located.record


def _thumbnail(root: Path) -> Path:
    path = _record(root).media[IMAGE_MEDIA_ID].thumbnail_path
    assert path is not None
    assert path.startswith('.boosty-downloader/thumbs/')
    return root / AUTHOR / path


def _payload(*, locked: bool = False, video_only: bool = False) -> dict[str, Any]:
    payload = synthetic_post()
    payload['hasAccess'] = not locked
    payload['data'] = (
        [] if locked else [ok_video_chunk() if video_only else image_chunk()]
    )
    return payload


async def test_thumbnail_saved_once_without_primary_bytes_or_page_changes(
    tmp_path: Path, requests: _Requests
) -> None:
    reporter = _QuietReporter()
    payload = synthetic_post()
    payload['data'] = [
        chunk for chunk in payload['data'] if chunk['type'] != 'hologram_message'
    ]
    async with TestServer(requests.app(payload)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)
        thumbnail = _thumbnail(tmp_path)
        assert thumbnail.read_bytes() == THUMBNAIL_PNG
        assert stats.media == MediaCounts(images=1, files=1, audio=1, boosty_videos=1)
        assert stats.downloaded_bytes == len(b'png bytesfile bytesmp3 bytesmp4 bytes')
        assert len(requests.primary) == 4
        assert requests.thumbnails == [f'/image/{IMAGE_ID}?fake-signed-query&mw=480']
        assert requests.auxiliary == ['/preview/full']
        page = tmp_path / AUTHOR / POST_DIR_NAME / 'post.html'
        assert '.boosty-downloader/thumbs/' not in page.read_text()
        before = _snapshot(page.parent)
        thumbnail_before = (thumbnail.read_bytes(), thumbnail.stat().st_mtime_ns)
        requests.clear()
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)
    requests.assert_empty()
    assert stats.downloaded_bytes == 0
    assert stats.media == MediaCounts()
    assert _snapshot(page.parent) == before
    assert (thumbnail.read_bytes(), thumbnail.stat().st_mtime_ns) == thumbnail_before
    assert reporter.warnings == []


async def test_deleted_thumbnail_directory_is_planned_read_only_then_rebuilt(
    tmp_path: Path, requests: _Requests
) -> None:
    async with TestServer(requests.app(_payload())) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        thumbnail = _thumbnail(tmp_path)
        thumbnail.unlink()
        thumbnail.parent.rmdir()
        original = _record(tmp_path).media[IMAGE_MEDIA_ID]
        page = tmp_path / AUTHOR / POST_DIR_NAME / 'post.html'
        page_before = (page.read_bytes(), page.stat().st_mtime_ns)
        before = _snapshot(tmp_path)
        requests.clear()
        plan = (await _dry_run(tmp_path, server.make_url('/'))).plan
        assert plan.updated_posts == 1
        assert plan.media == MediaCounts()
        requests.assert_empty()
        assert _snapshot(tmp_path) == before
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert requests.primary == []
    assert len(requests.thumbnails) == 1
    assert _thumbnail(tmp_path).read_bytes() == THUMBNAIL_PNG
    assert _record(tmp_path).media[IMAGE_MEDIA_ID] == original
    assert (page.read_bytes(), page.stat().st_mtime_ns) == page_before
    assert stats.media == MediaCounts()
    assert stats.downloaded_bytes == 0


async def test_video_only_post_content_reuses_preview_without_resizer(
    tmp_path: Path, requests: _Requests
) -> None:
    filters = [DownloadContentTypeFilter.post_content]
    async with TestServer(requests.app(_payload(video_only=True))) as server:
        stats = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), filters=filters
        )
    entry = _record(tmp_path).media[VIDEO_MEDIA_ID]
    assert entry.status is MediaStatus.pending
    assert entry.path is None
    assert entry.preview_path is not None
    assert entry.thumbnail_path is None
    assert requests.auxiliary == ['/preview/full']
    assert requests.primary == []
    assert requests.thumbnails == []
    assert stats.media == MediaCounts()
    assert stats.downloaded_bytes == 0


async def test_optional_errors_warn_once_without_failed_posts_or_media(
    tmp_path: Path, requests: _Requests
) -> None:
    payload = _payload()
    second = image_chunk()
    second.update(
        id='10000000-0000-4000-8000-000000000202',
        url='https://images.example/image/second',
    )
    payload['data'].append(second)
    reporter = _QuietReporter()
    async with TestServer(requests.app(payload, thumbnail_status=404)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)
    assert len(requests.primary) == 2
    assert len(requests.thumbnails) == 2
    assert len(reporter.warnings) == 1
    assert 'thumbnail' in reporter.warnings[0]
    assert reporter.errors == []
    assert stats.posts_failed == 0
    assert stats.posts_downloaded == 1
    assert stats.media == MediaCounts(images=2)
    assert stats.downloaded_bytes == 2 * len(b'png bytes')
    assert not (tmp_path / AUTHOR / 'failed_downloads.log').exists()
    assert all(
        entry.status is MediaStatus.downloaded
        for entry in _record(tmp_path).media.values()
    )
    assert all(
        entry.thumbnail_path is None for entry in _record(tmp_path).media.values()
    )


async def test_successful_thumbnail_survives_primary_peer_failure_and_retry(
    tmp_path: Path, requests: _Requests
) -> None:
    async with TestServer(requests.app(fail_first_file=True)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert requests.primary.count(f'/file/{FILE_ID}') == 2
    assert requests.primary.count(f'/image/{IMAGE_ID}') == 1
    assert len(requests.thumbnails) == 1
    assert _thumbnail(tmp_path).read_bytes() == THUMBNAIL_PNG
    assert stats.posts_failed == 0
    assert stats.media == MediaCounts(images=1, files=1, audio=1, boosty_videos=1)


async def test_removed_image_without_thumbnail_keeps_original_fallback_without_request(
    tmp_path: Path, requests: _Requests
) -> None:
    async with TestServer(requests.app(_payload(), thumbnail_status=404)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    entry = _record(tmp_path).media[IMAGE_MEDIA_ID]
    assert entry.thumbnail_path is None
    payload = _payload()
    payload['data'] = []
    requests.clear()
    async with TestServer(requests.app(payload)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    requests.assert_empty()
    removed = _record(tmp_path).media[IMAGE_MEDIA_ID]
    assert removed.removed_at is not None
    assert removed.status is MediaStatus.downloaded
    assert removed.path == entry.path
    folder = f'{AUTHOR}/{POST_DIR_NAME}'
    assert media_thumbnail_path(AUTHOR, folder, removed) == f'{folder}/{removed.path}'
    assert (tmp_path / folder / str(removed.path)).read_bytes() == b'png bytes'


async def test_existing_locked_teaser_backfills_thumbnail_without_original_transfer(
    tmp_path: Path, requests: _Requests
) -> None:
    async with TestServer(
        requests.app(_payload(locked=True), thumbnail_status=404)
    ) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    first = read_locked_posts(tmp_path, AUTHOR)[POST_ID]
    assert first.teaser_path is not None
    assert first.teaser_thumbnail_path is None
    original = tmp_path / AUTHOR / first.teaser_path
    before = (original.read_bytes(), original.stat().st_mtime_ns)
    requests.clear()
    async with TestServer(requests.app(_payload(locked=True))) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    locked = read_locked_posts(tmp_path, AUTHOR)[POST_ID]
    assert locked.teaser_thumbnail_path is not None
    assert (
        tmp_path / AUTHOR / locked.teaser_thumbnail_path
    ).read_bytes() == THUMBNAIL_PNG
    assert requests.thumbnails == [f'/teaser/{TEASER_ID}?fake-signed-query&mw=480']
    assert requests.auxiliary == []
    assert requests.primary == []
    assert (original.read_bytes(), original.stat().st_mtime_ns) == before
    assert stats.posts_locked == 1
    assert stats.posts_failed == 0
    assert stats.media == MediaCounts()


@pytest.mark.parametrize('locked', [False, True])
async def test_excluded_posts_do_not_fetch_thumbnails(
    tmp_path: Path, requests: _Requests, *, locked: bool
) -> None:
    async with TestServer(requests.app(_payload(locked=locked))) as server:
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), excluded_tags=('fixture',)
        )
    requests.assert_empty()
    assert not (tmp_path / AUTHOR / '.boosty-downloader/thumbs').exists()


async def test_cli_download_indexes_thumbnail_and_reuses_it_on_second_run(
    tmp_path: Path, requests: _Requests, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    _write_config(tmp_path)
    runner = CliRunner()
    args = ['download', AUTHOR, '-f', 'post_content', '-d', '1', '-o', str(root)]
    async with TestServer(requests.app(_payload())) as server:
        _local_network(monkeypatch, server, root)
        first = await asyncio.to_thread(runner.invoke, typer_app, args)
        assert first.exit_code == 0, first.exception or first.output
        thumbnail = _thumbnail(root)
        assert len(requests.thumbnails) == 1
        index = LibraryIndex(root)
        with index.connect() as connection:
            row = connection.execute(
                select(IndexMedia.thumbnail_path, IndexMedia.status, IndexMedia.size)
            ).one()
        assert row.thumbnail_path == thumbnail.relative_to(root).as_posix()
        assert row.status == 'downloaded'
        assert row.size == len(b'png bytes')
        requests.clear()
        second = await asyncio.to_thread(runner.invoke, typer_app, args)
    assert second.exit_code == 0, second.exception or second.output
    requests.assert_empty()


async def test_later_image_changes_index_cover_from_video_preview_to_original(
    tmp_path: Path, requests: _Requests, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    _write_config(tmp_path)
    runner = CliRunner()
    args = ['download', AUTHOR, '-f', 'post_content', '-d', '1', '-o', str(root)]
    async with TestServer(requests.app(_payload(video_only=True))) as server:
        _local_network(monkeypatch, server, root)
        result = await asyncio.to_thread(runner.invoke, typer_app, args)
        assert result.exit_code == 0, result.exception or result.output
    index = LibraryIndex(root)
    with index.connect() as connection:
        original_cover = connection.scalar(select(IndexPost.cover_path))
    assert original_cover is not None
    assert '/previews/' in original_cover
    assert requests.thumbnails == []
    requests.clear()
    payload = _payload()
    payload['data'].append(ok_video_chunk())
    async with TestServer(requests.app(payload)) as server:
        _local_network(monkeypatch, server, root)
        result = await asyncio.to_thread(runner.invoke, typer_app, args)
        assert result.exit_code == 0, result.exception or result.output
    entry = _record(root).media[IMAGE_MEDIA_ID]
    assert entry.path is not None
    with index.connect() as connection:
        assert (
            connection.scalar(select(IndexPost.cover_path))
            == f'{AUTHOR}/{POST_DIR_NAME}/{entry.path}'
        )
        image = connection.scalar(
            select(IndexMedia.thumbnail_path).where(
                IndexMedia.media_id == IMAGE_MEDIA_ID
            )
        )
    assert image == f'{AUTHOR}/{entry.thumbnail_path}'
    assert requests.primary == [f'/image/{IMAGE_ID}']
    assert len(requests.thumbnails) == 1
    assert requests.auxiliary == []
