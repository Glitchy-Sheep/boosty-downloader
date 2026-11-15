"""Atomic publication of library record and page bytes."""

import os
import time
from contextlib import suppress
from enum import IntEnum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final


class _WindowsFileError(IntEnum):
    access_denied = 5
    sharing_violation = 32
    lock_violation = 33


_REPLACE_ATTEMPTS: Final = 6
_INITIAL_RETRY_DELAY: Final = 0.01


def write_atomically(path: Path, data: bytes) -> None:
    """Publish complete bytes through a temporary file beside the destination."""
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode='wb',
            dir=path.parent,
            prefix=f'{path.name}.',
            suffix='.tmp',
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        _replace_after_readers_close(temporary_path, path)
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def _replace_after_readers_close(source: Path, destination: Path) -> None:
    """Allow brief Windows reader locks without exposing partial records."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            source.replace(destination)
        except PermissionError as error:  # noqa: PERF203 - bounded filesystem retry
            if (
                getattr(error, 'winerror', None) not in set(_WindowsFileError)
                or attempt == _REPLACE_ATTEMPTS - 1
            ):
                raise
            time.sleep(_INITIAL_RETRY_DELAY * 2**attempt)
        else:
            return
