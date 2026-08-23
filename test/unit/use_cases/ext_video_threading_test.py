"""yt-dlp must run off the event loop, stay cancellable, and report safely.

Before this, the blocking yt-dlp call froze every other download and the
progress display for the whole duration of an external video.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

import pytest

from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.domain.post_data_chunks import PostDataChunkExternalVideo
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideoDownloadStatus,
    ExtVideoInterruptedByUserError,
)

if TYPE_CHECKING:
    from boosty_downloader.application.di.download_context import DownloadContext
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO


def _status() -> ExternalVideoDownloadStatus:
    return ExternalVideoDownloadStatus(
        name='v',
        total_bytes=100,
        downloaded_bytes=10,
        speed=1.0,
        percentage=10.0,
        delta_bytes=10,
    )


class _ThreadAwareReporter:
    """Records which thread every progress update arrives on."""

    def __init__(self) -> None:
        self.update_threads: list[int] = []

    def create_task(self, *args: object, **kwargs: object) -> UUID:
        del args, kwargs
        return uuid4()

    def update_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        self.update_threads.append(threading.get_ident())

    def complete_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs


class _Context:
    def __init__(self, downloader: object, reporter: _ThreadAwareReporter) -> None:
        self.external_videos_downloader = downloader
        self.progress_reporter = reporter


def _use_case(context: _Context, destination: Path) -> DownloadSinglePostUseCase:
    return DownloadSinglePostUseCase(
        destination=destination,
        post_dto=cast('PostDTO', None),
        download_context=cast('DownloadContext', context),
    )


async def test_download_runs_off_the_loop_and_progress_lands_on_it(
    tmp_path: Path,
) -> None:
    """The loop thread must stay free; Rich must be touched only from the loop."""
    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}

    class _FakeDownloader:
        def download_video(
            self, *, url: str, destination_directory: Path, progress_hook: object
        ) -> Path:
            del url
            seen['download_thread'] = threading.get_ident()
            cast('object', progress_hook)(_status())  # type: ignore[operator]
            return destination_directory / 'v.mp4'

    reporter = _ThreadAwareReporter()
    use_case = _use_case(_Context(_FakeDownloader(), reporter), tmp_path)

    result = await use_case.download_external_videos(
        PostDataChunkExternalVideo(url='https://y/1')
    )
    await asyncio.sleep(0.05)  # let call_soon_threadsafe deliver the update

    assert seen['download_thread'] != loop_thread, 'yt-dlp must not run on the loop'
    assert reporter.update_threads == [loop_thread], (
        'progress must be marshalled onto the loop thread'
    )
    assert result == Path('external_videos/v.mp4')


async def test_cancellation_aborts_the_worker_thread(tmp_path: Path) -> None:
    """Ctrl+C must stop yt-dlp, not leave it downloading in a zombie thread."""
    started = threading.Event()
    aborted = threading.Event()

    class _LoopingDownloader:
        def download_video(
            self, *, url: str, destination_directory: Path, progress_hook: object
        ) -> Path:
            del url, destination_directory
            started.set()
            try:
                while True:
                    time.sleep(0.01)
                    cast('object', progress_hook)(_status())  # type: ignore[operator]
            except KeyboardInterrupt:
                aborted.set()
                raise ExtVideoInterruptedByUserError from None

    reporter = _ThreadAwareReporter()
    use_case = _use_case(_Context(_LoopingDownloader(), reporter), tmp_path)

    task = asyncio.create_task(
        use_case.download_external_videos(PostDataChunkExternalVideo(url='https://y/1'))
    )
    await asyncio.to_thread(started.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await asyncio.to_thread(aborted.wait, 2), (
        'the worker must abort via KeyboardInterrupt shortly after the cancel'
    )
