"""The path-length hint must fire on the real OS error and only on it."""

from __future__ import annotations

import errno

from boosty_downloader.infrastructure.path_sanitizer import (
    is_path_too_long_error,
)


def test_detects_the_posix_name_too_long_error() -> None:
    """Missing the errno means the user gets a raw OSError with no advice."""
    error = OSError(errno.ENAMETOOLONG, 'File name too long')

    assert is_path_too_long_error(error)


def test_detects_the_error_hidden_under_wrappers() -> None:
    """The OSError reaches the reporter wrapped into app errors via 'from e'."""
    cause = OSError(errno.ENAMETOOLONG, 'File name too long')
    wrapper = RuntimeError('download failed')
    wrapper.__cause__ = ValueError('io failed')
    wrapper.__cause__.__cause__ = cause

    assert is_path_too_long_error(wrapper)


def test_detects_the_windows_path_error_by_winerror() -> None:
    """Windows reports MAX_PATH overflow as WinError 206, not ENAMETOOLONG."""

    class _WindowsPathError(OSError):
        winerror = 206

    assert is_path_too_long_error(_WindowsPathError())


def test_ignores_unrelated_errors() -> None:
    """A false hint would send the user chasing folders for a network problem."""
    assert not is_path_too_long_error(OSError(errno.ENOENT, 'No such file'))
    assert not is_path_too_long_error(RuntimeError('boom'))
    assert not is_path_too_long_error(None)
