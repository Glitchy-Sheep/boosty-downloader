"""Publish complete media without replacing an occupied destination."""

from __future__ import annotations

import ctypes
import errno
import os
import sys
from dataclasses import dataclass
from functools import cache
from stat import FILE_ATTRIBUTE_REPARSE_POINT, S_ISREG
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class PublishedFile:
    """A complete file at its final path, with its actual size in bytes."""

    path: Path
    size: int


_LINUX_AT_FDCWD: Final = -100
_LINUX_RENAME_NOREPLACE: Final = 1
_MACOS_RENAME_EXCL: Final = 4
_UNSUPPORTED_RENAME_ERRORS: Final = frozenset(
    {errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}
)


def publish_completed_file(source: Path, destination: Path) -> PublishedFile:
    """
    Make a completed, closed regular file visible only at an absent final path.

    The caller owns the source and validates both paths within its output directory. No directories are created. Native rename consumes the source; the hardlink fallback retains it for caller cleanup. Failure to support either operation propagates without overwriting the destination.
    """
    size = _completed_file_size(source)
    _require_absent(destination)
    try:
        _rename_exclusively(source, destination)
    except OSError as error:
        if error.errno not in _UNSUPPORTED_RENAME_ERRORS:
            raise
        os.link(source, destination, follow_symlinks=False)
    return PublishedFile(path=destination, size=size)


def _completed_file_size(source: Path) -> int:
    info = source.lstat()
    attributes = getattr(info, 'st_file_attributes', 0)
    if not S_ISREG(info.st_mode) or attributes & FILE_ATTRIBUTE_REPARSE_POINT:
        message = f'Media source must be a regular file: {source}'
        raise ValueError(message)
    return info.st_size


def _require_absent(destination: Path) -> None:
    try:
        destination.lstat()
    except FileNotFoundError:
        return
    raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), destination)


def _rename_exclusively(source: Path, destination: Path) -> None:
    match sys.platform:
        case 'win32':
            source.rename(destination)
        case 'darwin':
            _rename_macos(source, destination)
        case 'linux':
            _rename_linux(source, destination)
        case _:
            raise OSError(errno.ENOSYS, 'Exclusive rename is not available')


@cache
def _c_library() -> ctypes.CDLL:
    return ctypes.CDLL(None, use_errno=True)


def _rename_linux(source: Path, destination: Path) -> None:
    try:
        rename = _c_library().renameat2
    except AttributeError as error:
        raise OSError(errno.ENOSYS, 'Exclusive rename is not available') from error
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    result = rename(
        _LINUX_AT_FDCWD,
        os.fsencode(source),
        _LINUX_AT_FDCWD,
        os.fsencode(destination),
        _LINUX_RENAME_NOREPLACE,
    )
    _check_rename_result(result, source, destination)


def _rename_macos(source: Path, destination: Path) -> None:
    try:
        rename = _c_library().renamex_np
    except AttributeError as error:
        raise OSError(errno.ENOSYS, 'Exclusive rename is not available') from error
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    result = rename(os.fsencode(source), os.fsencode(destination), _MACOS_RENAME_EXCL)
    _check_rename_result(result, source, destination)


def _check_rename_result(result: int, source: Path, destination: Path) -> None:
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), source, None, destination)
