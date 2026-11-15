"""Finish temporary media I/O before cancellation can release its workspace."""

from __future__ import annotations

import errno
import logging
from asyncio import CancelledError, get_running_loop, wait
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from asyncio import Future
    from collections.abc import AsyncGenerator
    from pathlib import Path
    from typing import BinaryIO, NoReturn

_Result = TypeVar('_Result')
_logger = logging.getLogger(__name__)


class MediaWriter:
    """Write one temporary file sequentially in its owning coroutine."""

    def __init__(self, file: BinaryIO) -> None:
        self._file = file

    async def write(self, data: bytes) -> None:
        """Finish the current write before returning or raising cancellation."""
        operation = get_running_loop().run_in_executor(None, self._file.write, data)
        written = await _finish_io(operation)
        if written != len(data):
            raise OSError(errno.EIO, 'Incomplete temporary media write')


@asynccontextmanager
async def open_media_writer(path: Path) -> AsyncGenerator[MediaWriter, None]:
    """
    Open an exclusive temporary output and finish closing it before exit.

    The caller owns the workspace and awaits each write in this context. Publication and workspace cleanup happen only after exit. Cancellation waits for in-flight opening, writing and closing, including repeated cancellation requests.
    """
    opening = get_running_loop().run_in_executor(None, _open_file, path)
    failure: BaseException | None = None
    try:
        yield MediaWriter(await _finish_io(opening))
    except BaseException as error:
        failure = error
        raise
    finally:
        await _close_opened_file(opening, failure)


def _open_file(path: Path) -> BinaryIO:
    return path.open('xb')


def _close_file(file: BinaryIO) -> None:
    file.close()


async def _finish_io(operation: Future[_Result]) -> _Result:
    cancellation: CancelledError | None = None
    while True:
        try:
            # Waiting does not cancel the worker or raise its I/O failure.
            await wait({operation})
        except CancelledError as error:
            if cancellation is None:
                cancellation = error
        if operation.done():
            break
    if cancellation is not None:
        if not operation.cancelled():
            raise cancellation from operation.exception()
        raise cancellation
    return operation.result()


async def _close_opened_file(
    opening: Future[BinaryIO], failure: BaseException | None
) -> None:
    if opening.cancelled() or opening.exception() is not None:
        return
    operation = get_running_loop().run_in_executor(None, _close_file, opening.result())
    try:
        await _finish_io(operation)
    except CancelledError as error:
        _raise_close_cancellation(error, failure)
    except OSError as error:
        if failure is None:
            raise
        _logger.warning('Could not close temporary media after a failure: %s', error)


def _raise_close_cancellation(
    cancellation: CancelledError, failure: BaseException | None
) -> NoReturn:
    if failure is None:
        raise cancellation
    if cancellation.__cause__ is not None:
        _logger.warning(
            'Temporary media closing also failed: %s', cancellation.__cause__
        )
    if isinstance(failure, CancelledError):
        raise failure
    raise cancellation from failure
