"""Bulk workers retain ownership across request cancellation and shutdown."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.domain.library_errors import LibraryWriteError
from boosty_downloader.domain.library_mutations import BulkMarkProgress
from boosty_downloader.viewer.api_models import BulkMarksProgressResponse
from boosty_downloader.viewer.mark_progress import (
    BulkMarksCoordinator,
    MarksBusyError,
    MarksClosingError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from concurrent.futures import Executor

    from boosty_downloader.viewer.mark_progress import ProgressCallback


async def _wait(event: threading.Event) -> None:
    assert await asyncio.to_thread(event.wait, 5)


async def test_progress_keeps_busy_and_awaits_a_disconnected_worker() -> None:
    coordinator = BulkMarksCoordinator()
    entered, release = threading.Event(), threading.Event()

    def work(progress: ProgressCallback) -> int:
        progress(BulkMarkProgress(3, 1, 1))
        entered.set()
        assert release.wait(5)
        progress(BulkMarkProgress(3, 3, 2))
        return 2

    caller = asyncio.create_task(coordinator.run('writer', work))
    try:
        await _wait(entered)
        assert coordinator.progress('writer') == BulkMarksProgressResponse(
            active=True, total=3, completed=1, changed=1
        )
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        with pytest.raises(MarksBusyError):
            await coordinator.run('writer', work)
        closing = asyncio.create_task(coordinator.close())
        await asyncio.sleep(0)
        assert not closing.done()
        assert coordinator.progress('writer').active
        release.set()
        await closing
        assert coordinator.progress('writer') == BulkMarksProgressResponse(active=False)
        with pytest.raises(MarksClosingError):
            await coordinator.run('writer', work)
    finally:
        release.set()
        await coordinator.close()


async def test_distinct_authors_have_separate_progress_and_no_completed_history() -> (
    None
):
    coordinator = BulkMarksCoordinator()
    entered, release = threading.Event(), threading.Event()

    def held(progress: ProgressCallback) -> int:
        progress(BulkMarkProgress(4, 2, 1))
        entered.set()
        assert release.wait(5)
        return 1

    def quick(progress: ProgressCallback) -> int:
        progress(BulkMarkProgress(0, 0, 0))
        return 0

    caller = asyncio.create_task(coordinator.run('first', held))
    try:
        await _wait(entered)
        assert await coordinator.run('second', quick) == 0
        assert coordinator.progress('second') == BulkMarksProgressResponse(active=False)
        assert coordinator.progress('first').completed == 2
        release.set()
        assert await caller == 1
        assert coordinator.progress('first') == BulkMarksProgressResponse(active=False)
    finally:
        release.set()
        await coordinator.close()


async def test_failure_releases_reservation_and_propagates_without_a_fake_count() -> (
    None
):
    coordinator = BulkMarksCoordinator()

    def fail(progress: ProgressCallback) -> int:
        progress(BulkMarkProgress(3, 1, 1))
        message = 'Failed index publication'
        raise LibraryWriteError(message)

    with pytest.raises(LibraryWriteError, match='Failed index'):
        await coordinator.run('writer', fail)
    assert not coordinator.progress('writer').active
    assert await coordinator.run('writer', lambda _progress: 2) == 2
    await coordinator.close()


async def test_a_late_callback_cannot_replace_a_successor_progress() -> None:
    coordinator = BulkMarksCoordinator()
    callbacks: list[ProgressCallback] = []
    entered, release = threading.Event(), threading.Event()

    def first(progress: ProgressCallback) -> int:
        callbacks.append(progress)
        return 1

    def second(progress: ProgressCallback) -> int:
        progress(BulkMarkProgress(10, 2, 2))
        entered.set()
        assert release.wait(5)
        return 2

    assert await coordinator.run('writer', first) == 1
    caller = asyncio.create_task(coordinator.run('writer', second))
    try:
        await _wait(entered)
        callbacks[0](BulkMarkProgress(999, 999, 999))
        assert coordinator.progress('writer').total == 10
        release.set()
        await caller
    finally:
        release.set()
        await coordinator.close()


async def test_executor_submission_failure_leaves_no_reservation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = BulkMarksCoordinator()
    loop = asyncio.get_running_loop()

    def fail(*_args: object) -> None:
        message = 'Cannot submit worker'
        raise RuntimeError(message)

    with monkeypatch.context() as patch:
        patch.setattr(loop, 'run_in_executor', fail)
        with pytest.raises(RuntimeError, match='Cannot submit'):
            await coordinator.run('writer', lambda _progress: 1)
    assert not coordinator.progress('writer').active
    assert await coordinator.run('writer', lambda _progress: 1) == 1
    await coordinator.close()


async def test_queued_worker_keeps_reservation_after_caller_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coordinator = BulkMarksCoordinator()
    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(max_workers=1)
    occupied, release = threading.Event(), threading.Event()
    called = threading.Event()
    original = loop.run_in_executor

    def occupy() -> None:
        occupied.set()
        assert release.wait(5)

    def work(_progress: ProgressCallback) -> int:
        called.set()
        return 1

    def schedule(
        _executor: Executor | None, fn: Callable[..., int | None], *args: object
    ) -> asyncio.Future[int | None]:
        return original(executor, fn, *args)

    blocker = original(executor, occupy)
    await _wait(occupied)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(
                loop,
                'run_in_executor',
                schedule,
            )
            caller = asyncio.create_task(coordinator.run('writer', work))
            await asyncio.sleep(0)
            assert coordinator.progress('writer') == BulkMarksProgressResponse(
                active=True
            )
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert not called.is_set()
            with pytest.raises(MarksBusyError):
                await coordinator.run('writer', work)
        release.set()
        await blocker
        await coordinator.close()
        assert called.is_set()
        assert not coordinator.progress('writer').active
    finally:
        release.set()
        await blocker
        await coordinator.close()
        executor.shutdown()
