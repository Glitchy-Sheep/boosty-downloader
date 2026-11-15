"""Optional thumbnail failures preserve canonical media and cancellation semantics."""

from __future__ import annotations

from asyncio import CancelledError, Event, create_task, wait_for
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest
from aiolimiter import AsyncLimiter
from support.synthetic_post import IMAGE_ID, POST_ID, image_chunk, synthetic_post

from boosty_downloader.application import thumbnail_sync
from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
)
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.ports import FailureLog, ProgressReporter
from boosty_downloader.application.post_download_state import (
    PostDownloadState,
    PostRunProgress,
)
from boosty_downloader.application.post_preparation import PostPreparer
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadTimeoutError,
)
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.media_publication import PublishedFile

if TYPE_CHECKING:
    from pathlib import Path

    from aiohttp_retry import RetryClient

    from boosty_downloader.application.post_preparation import PreparedPost
    from boosty_downloader.domain.stored_post import StoredPost
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )

AUTHOR = 'fixture-author'
MEDIA_ID = f'image:{IMAGE_ID}'
THUMBNAIL = '.boosty-downloader/thumbs/image.png'


@dataclass
class _Run:
    context: DownloadContext
    state: PostDownloadState
    prepared: PreparedPost
    transfer: AsyncMock
    reporter: Mock

    async def sync(self) -> None:
        await thumbnail_sync.ensure_image_thumbnail(
            self.context, self.state, MEDIA_ID, self.prepared.live.media[MEDIA_ID]
        )


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Run:
    store = JsonPostStore(tmp_path)
    reporter = Mock(spec=ProgressReporter)
    context = DownloadContext(
        author_name=AUTHOR,
        downloader_session=cast('RetryClient', None),
        external_videos_downloader=cast('ExternalVideosDownloader', None),
        post_store=store,
        library_root=tmp_path,
        filters=[DownloadContentTypeFilter.post_content],
        preferred_video_quality=BoostyOkVideoType.medium,
        progress_reporter=reporter,
        failed_logger=AsyncMock(spec=FailureLog),
        thumbnail_requests=AsyncLimiter(1000, time_period=1),
    )
    payload = synthetic_post()
    payload['data'] = [image_chunk()]
    prepared = PostPreparer(tmp_path, store, AUTHOR, BoostyOkVideoType.medium).prepare(
        PostDTO.model_validate(payload), context.filters, datetime.now(timezone.utc)
    )
    state = PostDownloadState(tmp_path, store, prepared, PostRunProgress())
    target = state.reserve(MEDIA_ID, 'original.png')
    original = tmp_path / state.folder / target.relative_path
    original.parent.mkdir(parents=True)
    original.write_bytes(b'original image')
    state.complete(MEDIA_ID, PublishedFile(original, len(b'original image')))
    state.mark_rendered(7)
    transfer = AsyncMock(return_value=THUMBNAIL)
    monkeypatch.setattr(thumbnail_sync, 'download_post_thumbnail', transfer)
    return _Run(context, state, prepared, transfer, reporter)


@pytest.mark.parametrize(
    'cancel', [CancelledError(), DownloadCancelledError('https://images.example')]
)
async def test_thumbnail_cancellation_propagates_and_preserves_saved_original(
    run: _Run, cancel: BaseException
) -> None:
    before = deepcopy(run.state.record)
    stats = deepcopy(run.context.run_statistics)
    run.transfer.side_effect = cancel

    with pytest.raises(ApplicationCancelledError) as raised:
        await run.sync()

    assert raised.value.post_uuid == POST_ID
    assert raised.value.__cause__ is cancel
    assert run.state.record == before
    assert run.context.run_statistics == stats
    assert (
        run.context.library_root / run.state.folder / 'images/original.png'
    ).read_bytes() == b'original image'
    run.reporter.warn.assert_not_called()


async def test_thumbnail_record_write_failure_is_not_downgraded_to_warning(
    run: _Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    thumbnail = run.context.library_root / AUTHOR / THUMBNAIL
    thumbnail.parent.mkdir(parents=True)
    thumbnail.write_bytes(b'published thumbnail')
    before = deepcopy(run.state.record)

    def fail_save(_folder: str, _record: StoredPost) -> None:
        message = 'canonical thumbnail save failed'
        raise OSError(message)

    monkeypatch.setattr(run.context.post_store, 'save_post', fail_save)

    with pytest.raises(OSError, match='canonical thumbnail save failed'):
        await run.sync()

    assert run.state.record == before
    assert thumbnail.read_bytes() == b'published thumbnail'
    run.reporter.warn.assert_not_called()


async def test_optional_warning_is_shared_by_all_attempts_in_one_run(run: _Run) -> None:
    before = deepcopy(run.state.record)
    run.transfer.side_effect = DownloadTimeoutError('https://images.example')

    await run.sync()
    await run.sync()

    assert run.transfer.await_count == 2
    run.reporter.warn.assert_called_once()
    assert run.context.thumbnail_warning_reported
    assert run.state.record == before


def test_default_thumbnail_limiter_allows_one_request_per_second(run: _Run) -> None:
    context = DownloadContext(
        author_name=run.context.author_name,
        downloader_session=run.context.downloader_session,
        external_videos_downloader=run.context.external_videos_downloader,
        post_store=run.context.post_store,
        library_root=run.context.library_root,
        filters=run.context.filters,
        preferred_video_quality=run.context.preferred_video_quality,
        progress_reporter=run.context.progress_reporter,
        failed_logger=run.context.failed_logger,
    )
    assert context.thumbnail_requests.max_rate == 1
    assert context.thumbnail_requests.time_period == 1
    assert context.thumbnail_requests is not run.context.thumbnail_requests


class _ObservedLimiter(AsyncLimiter):
    def __init__(self) -> None:
        super().__init__(1, time_period=3600)
        self.entered = Event()

    async def acquire(self, amount: float = 1) -> None:
        self.entered.set()
        await super().acquire(amount)


async def test_exhausted_shared_limiter_blocks_transport_and_remains_cancellable(
    run: _Run,
) -> None:
    limiter = _ObservedLimiter()
    await limiter.acquire()
    limiter.entered.clear()
    run.context.thumbnail_requests = limiter
    before = deepcopy(run.state.record)
    task = create_task(run.sync())
    try:
        await wait_for(limiter.entered.wait(), timeout=1)
        run.transfer.assert_not_awaited()
        assert not task.done()
    finally:
        task.cancel()
        with pytest.raises(ApplicationCancelledError):
            await task
    assert run.state.record == before
    run.reporter.warn.assert_not_called()
