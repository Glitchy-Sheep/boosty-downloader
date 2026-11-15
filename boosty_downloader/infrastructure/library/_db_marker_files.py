"""Read and publish complete C-library ownership records without replacement."""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Final

from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.media_publication import publish_completed_file

if TYPE_CHECKING:
    from os import stat_result

_MAX_MARKER_BYTES: Final = 4096


def validate_marker_path(path: Path) -> None:
    """Reject redirected directories and shared ownership records."""
    _validate_marker_parents(path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if is_link(info) or not S_ISREG(info.st_mode) or info.st_nlink != 1:
        message = f'Library ownership record must be an ordinary unshared file: {path}'
        raise LibraryDatabaseError(message)


def _validate_marker_parents(path: Path) -> None:
    for directory in reversed(path.parents):
        try:
            info = directory.lstat()
        except FileNotFoundError:
            continue
        if is_link(info) or not S_ISDIR(info.st_mode):
            message = (
                f'Library metadata parent must be an ordinary directory: {directory}'
            )
            raise LibraryDatabaseError(message)


def read_marker_bytes(path: Path) -> bytes | None:
    """Read one bounded ordinary record, preserving absent or unreadable paths."""
    validate_marker_path(path)
    try:
        expected = path.lstat()
    except FileNotFoundError:
        return None
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as stream:
        actual = os.fstat(stream.fileno())
        if not os.path.samestat(expected, actual):
            message = f'Library ownership record changed while being read: {path}'
            raise LibraryDatabaseError(message)
        data = stream.read(_MAX_MARKER_BYTES + 1)
    if len(data) > _MAX_MARKER_BYTES:
        message = f'Library ownership record is too large: {path}'
        raise LibraryDatabaseError(message)
    return data


def publish_marker(path: Path, data: bytes) -> None:
    """Publish fsynced bytes exclusively; a concurrent destination is never replaced."""
    validate_marker_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    validate_marker_path(path)
    temporary_path: Path | None = None
    identity: stat_result | None = None
    try:
        with NamedTemporaryFile(
            mode='wb',
            dir=path.parent,
            prefix=f'.{path.stem}.',
            suffix='.tmp',
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            identity = os.fstat(temporary.fileno())
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        validate_marker_path(path)
        publish_completed_file(temporary_path, path)
        _flush_directory(path.parent)
    finally:
        if temporary_path is not None and identity is not None:
            _remove_owned_temporary(temporary_path, identity)


def _flush_directory(path: Path) -> None:
    if os.name == 'nt':
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_owned_temporary(path: Path, expected: stat_result) -> None:
    with suppress(OSError, LibraryDatabaseError):
        _validate_marker_parents(path)
        actual = path.lstat()
        if not is_link(actual) and os.path.samestat(expected, actual):
            path.unlink()
