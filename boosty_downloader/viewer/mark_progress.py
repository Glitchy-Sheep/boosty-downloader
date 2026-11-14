"""Bounded progress and lifetime ownership for bulk mark workers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING, TypeAlias

from boosty_downloader.viewer.api_models import BulkMarksProgressResponse

if TYPE_CHECKING:
    from collections.abc import Callable

    from boosty_downloader.domain.library_mutations import BulkMarkProgress

ProgressCallback: TypeAlias = 'Callable[[BulkMarkProgress], None]'
BulkOperation: TypeAlias = 'Callable[[ProgressCallback], int | None]'
_LOGGER = logging.getLogger(__name__)


class MarksBusyError(RuntimeError):
    """A bulk operation already owns this author's active progress."""


class MarksClosingError(RuntimeError):
    """The viewer is shutting down and cannot accept another bulk."""


@dataclass(slots=True)
class _ActiveBulk:
    progress: BulkMarkProgress | None = None


class BulkMarksCoordinator:
    """Keep a reservation until its worker ends, even after a request disconnects."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._active: dict[str, _ActiveBulk] = {}
        self._workers: set[asyncio.Future[int | None]] = set()
        self._closing = False

    async def run(self, author: str, operation: BulkOperation) -> int | None:
        """Reserve before scheduling; only the worker releases a submitted operation."""
        active = self._reserve(author)
        worker = None
        try:
            worker = asyncio.get_running_loop().run_in_executor(
                None, self._run_worker, author, active, operation
            )
            self._workers.add(worker)
            worker.add_done_callback(self._worker_done)
            return await asyncio.shield(worker)
        finally:
            if worker is None:
                self._release(author, active)

    def progress(self, author: str) -> BulkMarksProgressResponse:
        """Read coherent counts without waiting for canonical storage work."""
        with self._lock:
            active = self._active.get(author)
            if active is None:
                return BulkMarksProgressResponse(active=False)
            progress = active.progress
            if progress is None:
                return BulkMarksProgressResponse(active=True)
            return BulkMarksProgressResponse(
                active=True,
                total=progress.total,
                completed=progress.completed,
                changed=progress.changed,
            )

    async def close(self) -> None:
        """Stop admission and await every submitted worker without cancelling it."""
        self._closing = True
        if self._workers:
            await asyncio.gather(
                *(asyncio.shield(worker) for worker in tuple(self._workers)),
                return_exceptions=True,
            )

    def _reserve(self, author: str) -> _ActiveBulk:
        with self._lock:
            if self._closing:
                message = 'The viewer is shutting down.'
                raise MarksClosingError(message)
            if author in self._active:
                message = 'A bulk mark operation is already running for this author.'
                raise MarksBusyError(message)
            active = _ActiveBulk()
            self._active[author] = active
            return active

    def _publish(
        self, author: str, active: _ActiveBulk, value: BulkMarkProgress
    ) -> None:
        with self._lock:
            if self._active.get(author) is active:
                active.progress = value

    def _release(self, author: str, active: _ActiveBulk) -> None:
        with self._lock:
            if self._active.get(author) is active:
                del self._active[author]

    def _run_worker(
        self, author: str, active: _ActiveBulk, operation: BulkOperation
    ) -> int | None:
        try:
            return operation(lambda value: self._publish(author, active, value))
        finally:
            self._release(author, active)

    def _worker_done(self, worker: asyncio.Future[int | None]) -> None:
        self._workers.discard(worker)
        if worker.cancelled():
            return
        error = worker.exception()
        if error is not None:
            _LOGGER.error(
                'Bulk mark operation failed',
                exc_info=(type(error), error, error.__traceback__),
            )
