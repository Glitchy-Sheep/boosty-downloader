"""Restoring selected local deletions preserves other files and author removals."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest
from aiohttp.test_utils import TestServer
from e2e.download_flow_test import (
    AUTHOR,
    POST_DIR_NAME,
    _build_app,
    _dry_run,
    _QuietReporter,
    _run_download,
)
from support.synthetic_post import FILE_ID, FILE_SIZE, POST_ID, VIDEO_ID, synthetic_post

from boosty_downloader.application import post_retry as post_retry_module
from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

    from boosty_downloader.domain.stored_post import StoredPost

FILE_MEDIA_ID = f'file:{FILE_ID}'
VIDEO_MEDIA_ID = f'boosty_video:{VIDEO_ID}'


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


def _record(root: Path) -> StoredPost:
    located = JsonPostStore(root).find_post(AUTHOR, POST_ID)
    assert located is not None
    assert located.record is not None
    return located.record


def _media_file(root: Path, media_id: str) -> Path:
    path = _record(root).media[media_id].path
    assert path is not None
    return root / AUTHOR / POST_DIR_NAME / path


def _page(root: Path) -> str:
    return (root / AUTHOR / POST_DIR_NAME / 'post.html').read_text(encoding='utf-8')


def _without_piece(media_id: str) -> dict[str, Any]:
    post = synthetic_post()
    post['data'] = [chunk for chunk in post['data'] if chunk.get('id') != media_id]
    return post


@pytest.mark.parametrize('post_id', [None, POST_ID], ids=['bulk', 'single'])
async def test_deleted_file_stays_deleted_until_restore_matches_the_read_only_plan(
    tmp_path: Path,
    post_id: str | None,
) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        file = _media_file(tmp_path, FILE_MEDIA_ID)
        file.unlink()
        served.clear()
        before = _snapshot(tmp_path)
        ordinary_plan = await _dry_run(tmp_path, server.make_url('/'))
        restore_plan = await _dry_run(
            tmp_path, server.make_url('/'), restore_missing=True
        )
        assert ordinary_plan.plan.media == MediaCounts()
        assert restore_plan.plan.media == MediaCounts(files=1)
        assert restore_plan.plan.known_bytes == FILE_SIZE
        assert _snapshot(tmp_path) == before
        assert served == []

        for _ in range(2):
            stats = await _run_download(
                tmp_path, server.make_url('/'), _QuietReporter(), post_id=post_id
            )
            assert stats.media_deleted == 1
            assert stats.media == MediaCounts()
            assert _record(tmp_path).media[FILE_MEDIA_ID].status is MediaStatus.deleted
            assert 'File deleted from disk' in _page(tmp_path)
        assert served == []

        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            post_id=post_id,
            restore_missing=True,
        )

    assert served == [f'/file/{FILE_ID}']
    assert stats.media == restore_plan.plan.media
    assert stats.media_deleted == 0
    assert file.read_bytes() == b'file bytes'
    assert _record(tmp_path).media[FILE_MEDIA_ID].status is MediaStatus.downloaded
    assert 'deleted from disk' not in _page(tmp_path)
    assert 'href="files/fixture-archive.zip"' in _page(tmp_path)


async def test_restore_filter_leaves_other_deleted_media_counted(
    tmp_path: Path,
) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        _media_file(tmp_path, FILE_MEDIA_ID).unlink()
        video = _media_file(tmp_path, VIDEO_MEDIA_ID)
        video.unlink()
        served.clear()
        filters = [DownloadContentTypeFilter.files]
        before = _snapshot(tmp_path)
        plan = await _dry_run(
            tmp_path, server.make_url('/'), restore_missing=True, filters=filters
        )
        assert plan.plan.media == MediaCounts(files=1)
        assert _snapshot(tmp_path) == before
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            restore_missing=True,
            filters=filters,
        )

    assert served == [f'/file/{FILE_ID}']
    assert stats.media_deleted == 1
    assert stats.media == plan.plan.media
    assert not video.exists()
    assert _record(tmp_path).media[VIDEO_MEDIA_ID].status is MediaStatus.deleted
    assert 'Video deleted from disk' in _page(tmp_path)


@pytest.mark.parametrize('restore_missing', [False, True])
async def test_reencoded_video_keeps_its_bytes_and_updates_recorded_size(
    tmp_path: Path,
    *,
    restore_missing: bool,
) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        video = _media_file(tmp_path, VIDEO_MEDIA_ID)
        video.write_bytes(b're-encoded video with another size')
        original = _FileState(video.read_bytes(), video.stat().st_mtime_ns)
        served.clear()
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            restore_missing=restore_missing,
        )

    assert served == []
    assert stats.media_deleted == 0
    assert _FileState(video.read_bytes(), video.stat().st_mtime_ns) == original
    assert _record(tmp_path).media[VIDEO_MEDIA_ID].size == len(original.content or b'')
    assert _record(tmp_path).media[VIDEO_MEDIA_ID].status is MediaStatus.downloaded


@pytest.mark.parametrize('restore_missing', [False, True])
async def test_deleted_author_removed_piece_is_never_restored_or_counted(
    tmp_path: Path,
    *,
    restore_missing: bool,
) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    file = _media_file(tmp_path, FILE_MEDIA_ID)
    served.clear()
    async with TestServer(
        _build_app(served, payload=_without_piece(FILE_ID))
    ) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        assert 'Removed by the author' in _page(tmp_path)
        file.unlink()
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            restore_missing=restore_missing,
        )

    assert served == []
    assert stats.media_deleted == 0
    assert not file.exists()
    media = _record(tmp_path).media[FILE_MEDIA_ID]
    assert media.status is MediaStatus.deleted
    assert media.removed_at is not None
    assert 'Removed by the author' not in _page(tmp_path)
    assert 'fixture-archive.zip' not in _page(tmp_path)


@pytest.mark.parametrize('removed_by_author', [False, True])
@pytest.mark.parametrize('restore_missing', [False, True])
async def test_copied_back_file_returns_to_the_page_without_a_download(
    tmp_path: Path,
    *,
    removed_by_author: bool,
    restore_missing: bool,
) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    file = _media_file(tmp_path, FILE_MEDIA_ID)
    file.unlink()
    payload = _without_piece(FILE_ID) if removed_by_author else synthetic_post()
    served.clear()
    async with TestServer(_build_app(served, payload=payload)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        assert _record(tmp_path).media[FILE_MEDIA_ID].status is MediaStatus.deleted
        restored_bytes = b'copy returned by the user'
        file.write_bytes(restored_bytes)
        original = _FileState(file.read_bytes(), file.stat().st_mtime_ns)
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            restore_missing=restore_missing,
        )

    assert served == []
    assert stats.media_deleted == 0
    assert _FileState(file.read_bytes(), file.stat().st_mtime_ns) == original
    media = _record(tmp_path).media[FILE_MEDIA_ID]
    assert media.status is MediaStatus.downloaded
    assert media.size == len(restored_bytes)
    assert 'href="files/fixture-archive.zip"' in _page(tmp_path)
    assert ('Removed by the author' in _page(tmp_path)) is removed_by_author


@pytest.mark.parametrize(
    'first_status',
    [HTTPStatus.NOT_FOUND, HTTPStatus.FORBIDDEN],
    ids=['retry', 'refresh'],
)
async def test_retry_replaces_the_posts_deleted_count_after_author_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first_status: HTTPStatus,
) -> None:
    async def no_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(post_retry_module.asyncio, 'sleep', no_sleep)
    async with TestServer(_build_app([])) as server:
        await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            filters=[
                DownloadContentTypeFilter.post_content,
                DownloadContentTypeFilter.boosty_videos,
            ],
        )
    video = _media_file(tmp_path, VIDEO_MEDIA_ID)
    video.unlink()
    served: list[str] = []
    refreshed = _without_piece(VIDEO_ID)
    app = _build_app(
        served,
        fail_first_file=True,
        first_file_status=first_status,
        refreshed_payload=refreshed,
    )
    async with TestServer(app) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())

    assert served.count(f'/file/{FILE_ID}') == 2
    assert not video.exists()
    assert stats.posts_failed == 0
    assert stats.posts_downloaded == 1
    expected_deleted = int(first_status is HTTPStatus.NOT_FOUND)
    assert stats.media_deleted == expected_deleted
    assert ('Video deleted from disk' in _page(tmp_path)) is bool(expected_deleted)


async def test_deleted_whole_post_folder_is_downloaded_as_new_without_restore(
    tmp_path: Path,
) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        folder = tmp_path / AUTHOR / POST_DIR_NAME
        (folder / 'viewer.json').write_bytes(b'old personal marks')
        shutil.rmtree(folder)
        served.clear()
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())

    assert len(served) == 4
    assert stats.posts_downloaded == 1
    assert stats.media_deleted == 0
    assert (folder / 'post.html').is_file()
    assert not (folder / 'viewer.json').exists()
    assert all(
        piece.status is MediaStatus.downloaded
        for piece in _record(tmp_path).media.values()
    )
