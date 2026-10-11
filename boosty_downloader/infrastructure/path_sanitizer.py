"""Filesystem path errors and shared portable-name exports."""

import errno

from boosty_downloader.domain.path_names import (
    MAX_NAME_BYTES,
    compose_filename,
    sanitize_filename,
)

__all__ = [
    'MAX_NAME_BYTES',
    'PATH_TOO_LONG_HINT',
    'compose_filename',
    'is_path_too_long_error',
    'sanitize_filename',
]

# Windows raises this instead of ENAMETOOLONG when the whole path
# exceeds MAX_PATH (260 units by default).
_WINERROR_PATH_TOO_LONG = 206

# Generated names always fit the per-name limit, so this error means
# the user's destination directory is too deep.
PATH_TOO_LONG_HINT = (
    'the full path exceeded the OS limit - '
    'move the destination folder closer to the drive root'
)


def is_path_too_long_error(error: BaseException | None) -> bool:
    """Check the error or any of its causes for the OS path-length failure."""
    while error is not None:
        if isinstance(error, OSError) and (
            error.errno == errno.ENAMETOOLONG
            or getattr(error, 'winerror', None) == _WINERROR_PATH_TOO_LONG
        ):
            return True
        error = error.__cause__
    return False
