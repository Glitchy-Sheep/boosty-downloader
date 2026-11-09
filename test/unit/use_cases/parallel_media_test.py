"""Parallel media work preserves durable outcomes, body order and cancellation."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from support.synthetic_post import IMAGE_ID, file_chunk, image_chunk, synthetic_post

from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.ports import FailureLog, ProgressReporter
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.media_publication import PublishedFile
from boosty_downloader.infrastructure.post_media_downloader import (
    MediaDownloadError,
    PostMediaDownloader,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aiohttp_retry import RetryClient

    from boosty_downloader.domain.post_data_chunks import PostDataChunkFile
    from boosty_downloader.domain.stored_post import StoredPost
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )
    from boosty_downloader.infrastructure.media_transfer import ReserveMediaPath
    from boosty_downloader.infrastructure.post_media_downloader import ProgressCallback


def _file(index: int) -> dict[str, object]:
    return {**file_chunk(), 'id': f'f{index}', 'title': f'file-{index}.bin', 'size': 1}


def _use_case(
    root: Path, chunks: list[dict[str, object]], media: Mock
) -> DownloadSinglePostUseCase:
    payload = synthetic_post()
    payload['data'] = chunks
    reporter = Mock(spec=ProgressReporter)
    reporter.create_task.return_value = uuid4()
    context = DownloadContext(
        author_name='author',
        downloader_session=cast('RetryClient', None),
        external_videos_downloader=cast('ExternalVideosDownloader', None),
        post_store=JsonPostStore(root),
        library_root=root,
        filters=list(DownloadContentTypeFilter),
        preferred_video_quality=BoostyOkVideoType.medium,
        progress_reporter=reporter,
        failed_logger=AsyncMock(spec=FailureLog),
    )
    with patch(
        'boosty_downloader.application.use_cases.download_single_post.PostMediaDownloader',
        return_value=media,
    ):
        return DownloadSinglePostUseCase(root, PostDTO.model_validate(payload), context)


def _record(use_case: DownloadSinglePostUseCase) -> StoredPost:
    located = use_case.context.post_store.find_post('author', use_case.post_dto.id)
    assert located is not None
    assert located.record is not None
    return located.record


def _save(filename: str, reserve: ReserveMediaPath) -> PublishedFile:
    target = reserve(filename)
    path = target.library_root / target.post_folder / target.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x')
    return PublishedFile(path, size=1)


async def test_downloads_overlap_with_a_cap_and_page_keeps_author_order(
    tmp_path: Path,
) -> None:
    started = [asyncio.Event() for _ in range(6)]
    release = [asyncio.Event() for _ in range(6)]
    finished = [asyncio.Event() for _ in range(6)]
    completion_order: list[int] = []
    active = maximum = 0

    async def download(
        file: PostDataChunkFile,
        on_progress: ProgressCallback,
        *,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        del on_progress
        nonlocal active, maximum
        index = int(file.id.removeprefix('f'))
        active += 1
        maximum = max(maximum, active)
        started[index].set()
        await release[index].wait()
        result = _save(file.filename, reserve)
        active -= 1
        completion_order.append(index)
        finished[index].set()
        return result

    media = Mock(spec=PostMediaDownloader)
    media.download_file = AsyncMock(side_effect=download)
    use_case = _use_case(tmp_path, [_file(n) for n in range(6)], media)
    task = asyncio.create_task(use_case.execute())
    try:
        await asyncio.wait_for(started[3].wait(), timeout=2)
        assert not started[4].is_set()
        release[3].set()
        await asyncio.wait_for(started[4].wait(), timeout=2)
        release[4].set()
        await asyncio.wait_for(started[5].wait(), timeout=2)
        for index in [5, 2, 1, 0]:
            release[index].set()
            await asyncio.wait_for(finished[index].wait(), timeout=2)
        await task
    finally:
        for event in release:
            event.set()
        await asyncio.gather(task, return_exceptions=True)

    assert maximum == 4
    assert completion_order == [3, 4, 5, 2, 1, 0]
    assert not (use_case.destination / 'post.html').exists()
    use_case.finalize()
    page = (use_case.destination / 'post.html').read_text(encoding='utf-8')
    positions = [page.index(f'href="files/file-{n}.bin"') for n in range(6)]
    assert positions == sorted(positions)
    assert all(
        entry.status is MediaStatus.downloaded
        for entry in _record(use_case).media.values()
    )
    assert use_case.context.run_statistics.posts_downloaded == 0
    use_case.record_success()
    assert use_case.context.run_statistics.posts_downloaded == 1


async def test_failed_file_allows_siblings_to_finish_and_persists_each_outcome(
    tmp_path: Path,
) -> None:
    failed = asyncio.Event()
    finished: list[str] = []

    async def download(
        file: PostDataChunkFile,
        on_progress: ProgressCallback,
        *,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        del on_progress
        if file.id == 'f0':
            failed.set()
            message = 'dead link'
            raise MediaDownloadError(message, resource_url=file.url)
        await failed.wait()
        await asyncio.sleep(0)
        result = _save(file.filename, reserve)
        finished.append(file.id)
        return result

    media = Mock(spec=PostMediaDownloader)
    media.download_file = AsyncMock(side_effect=download)
    use_case = _use_case(tmp_path, [_file(n) for n in range(4)], media)

    with pytest.raises(ApplicationFailedDownloadError) as info:
        await use_case.execute()

    assert 'dead link' in info.value.message
    assert set(finished) == {'f1', 'f2', 'f3'}
    record = _record(use_case)
    assert record.media['file:f0'].status is MediaStatus.failed
    assert all(
        record.media[f'file:f{n}'].status is MediaStatus.downloaded for n in range(1, 4)
    )
    use_case.finalize()
    page = (use_case.destination / 'post.html').read_text(encoding='utf-8')
    assert 'dead link' in page
    assert all(f'href="files/file-{n}.bin"' in page for n in range(1, 4))
    assert use_case.context.run_statistics.posts_downloaded == 0


async def test_failed_image_becomes_a_placeholder_then_retry_replaces_it(
    tmp_path: Path,
) -> None:
    media = Mock(spec=PostMediaDownloader)
    media.download_image = AsyncMock(
        side_effect=MediaDownloadError('dead image', 'https://images.example/image')
    )
    use_case = _use_case(tmp_path, [image_chunk()], media)

    with pytest.raises(ApplicationFailedDownloadError):
        await use_case.execute()
    use_case.finalize()
    assert 'dead image' in (use_case.destination / 'post.html').read_text(
        encoding='utf-8'
    )
    assert _record(use_case).media[f'image:{IMAGE_ID}'].status is MediaStatus.failed

    async def download(
        image: object, on_progress: ProgressCallback, *, reserve: ReserveMediaPath
    ) -> PublishedFile:
        del image, on_progress
        return _save('picture.png', reserve)

    media.download_image = AsyncMock(side_effect=download)
    await use_case.execute()
    use_case.finalize()
    page = (use_case.destination / 'post.html').read_text(encoding='utf-8')
    assert 'src="images/picture.png"' in page
    assert 'dead image' not in page
    assert _record(use_case).media[f'image:{IMAGE_ID}'].status is MediaStatus.downloaded


async def test_fresh_attempt_uses_saved_files_in_its_complete_page(
    tmp_path: Path,
) -> None:
    async def download_file(
        file: PostDataChunkFile,
        on_progress: ProgressCallback,
        *,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        del on_progress
        return _save(file.filename, reserve)

    media = Mock(spec=PostMediaDownloader)
    media.download_file = AsyncMock(side_effect=download_file)
    media.download_image = AsyncMock(
        side_effect=MediaDownloadError('dead image', 'https://images.example/image')
    )
    chunks = [image_chunk(), _file(0)]
    use_case = _use_case(tmp_path, chunks, media)
    with pytest.raises(ApplicationFailedDownloadError):
        await use_case.execute()

    async def download_image(
        image: object, on_progress: ProgressCallback, *, reserve: ReserveMediaPath
    ) -> PublishedFile:
        del image, on_progress
        return _save('picture.png', reserve)

    media.download_image = AsyncMock(side_effect=download_image)
    retry = _use_case(tmp_path, chunks, media)
    await retry.execute()
    retry.finalize()

    media.download_file.assert_awaited_once()
    page = (retry.destination / 'post.html').read_text(encoding='utf-8')
    assert page.index('src="images/picture.png"') < page.index(
        'href="files/file-0.bin"'
    )
    assert all(
        entry.status is MediaStatus.downloaded
        for entry in _record(retry).media.values()
    )


async def test_outer_cancel_waits_for_children_and_preserves_application_error(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    cleaning = asyncio.Event()
    allow_cleanup = asyncio.Event()
    active = 0

    async def download(
        file: PostDataChunkFile,
        on_progress: ProgressCallback,
        *,
        reserve: ReserveMediaPath,
    ) -> PublishedFile:
        del file, on_progress, reserve
        nonlocal active
        active += 1
        if active == 3:
            started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            await allow_cleanup.wait()
            active -= 1
        pytest.fail('The transfer must be cancelled')

    media = Mock(spec=PostMediaDownloader)
    media.download_file = AsyncMock(side_effect=download)
    use_case = _use_case(tmp_path, [_file(n) for n in range(3)], media)
    task = asyncio.create_task(use_case.execute())
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        await asyncio.wait_for(cleaning.wait(), timeout=2)
        assert not task.done()
    finally:
        allow_cleanup.set()
    with pytest.raises(ApplicationCancelledError):
        await task
    assert active == 0
    assert use_case.context.run_statistics.posts_downloaded == 0
    assert all(
        entry.status is MediaStatus.pending
        for entry in _record(use_case).media.values()
    )
