"""Identify v5 libraries without adopting or changing older downloads."""

from __future__ import annotations

import json
import os
from contextlib import suppress
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from boosty_downloader.domain.post_folder import parse_post_folder_id
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.media_publication import publish_completed_file

if TYPE_CHECKING:
    from os import stat_result

LIBRARY_FORMAT_VERSION: Final = 5
LIBRARY_MARKER_PATH: Final = Path('.boosty-downloader/library.json')
_MAX_MARKER_BYTES: Final = 1024


class LibraryCompatibilityError(ValueError):
    """The destination cannot safely be used as a v5 library."""


class _LibraryMarker(BaseModel):
    model_config = ConfigDict(extra='forbid')

    format_version: int = Field(strict=True)


def check_library_compatibility(root: Path) -> None:
    """Reject older or invalid libraries without writing or reading post contents."""
    try:
        _check_library(root.resolve())
    except (OSError, RuntimeError) as error:
        message = f'Cannot inspect library {root}: {error}'
        raise LibraryCompatibilityError(message) from error


def initialize_library(root: Path) -> None:
    """Mark an accepted library once; preserve and validate a concurrent marker."""
    try:
        resolved = root.resolve()
        if _check_library(resolved):
            return
        _create_directory(resolved / LIBRARY_MARKER_PATH.parent)
        if not _check_library(resolved):
            _publish_marker(resolved)
    except (OSError, RuntimeError) as error:
        message = f'Cannot initialize library {root}: {error}'
        raise LibraryCompatibilityError(message) from error


def _check_library(root: Path) -> bool:
    if not _existing_directory(root):
        return False
    if _read_marker(root):
        return True
    for author in root.iterdir():
        if _scanned_directory(author):
            _check_author_folders(root, author)
    return False


def _check_author_folders(root: Path, author: Path) -> None:
    for post in author.iterdir():
        if _scanned_directory(post) and parse_post_folder_id(post.name) is not None:
            message = (
                f'Older or unmarked downloads found in {root}. '
                'Choose another destination directory for v5. Keep this folder '
                'while it contains posts that Boosty no longer serves.'
            )
            raise LibraryCompatibilityError(message)


def _read_marker(root: Path) -> bool:
    marker = root / LIBRARY_MARKER_PATH
    if not _existing_directory(marker.parent):
        return False
    info = _optional_lstat(marker)
    if info is None:
        return False
    if is_link(info) or not S_ISREG(info.st_mode):
        message = f'Library marker must be an ordinary file: {marker}'
        raise LibraryCompatibilityError(message)
    _validate_marker(marker, _read_marker_bytes(marker, info))
    return True


def _read_marker_bytes(marker: Path, expected: stat_result) -> bytes:
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(marker, flags)
    with os.fdopen(descriptor, 'rb') as source:
        actual = os.fstat(source.fileno())
        if (
            is_link(actual)
            or not S_ISREG(actual.st_mode)
            or not os.path.samestat(expected, actual)
        ):
            message = f'Library marker changed while being read: {marker}'
            raise LibraryCompatibilityError(message)
        return source.read(_MAX_MARKER_BYTES + 1)


def _validate_marker(marker: Path, data: bytes) -> None:
    if len(data) > _MAX_MARKER_BYTES:
        message = f'Invalid library marker: {marker}'
        raise LibraryCompatibilityError(message)
    try:
        record = _LibraryMarker.model_validate_json(data)
    except ValidationError as error:
        message = f'Invalid library marker: {marker}'
        raise LibraryCompatibilityError(message) from error
    if record.format_version != LIBRARY_FORMAT_VERSION:
        message = (
            f'Unsupported library format {record.format_version} in {marker}; '
            f'this version requires format {LIBRARY_FORMAT_VERSION}.'
        )
        raise LibraryCompatibilityError(message)


def _optional_lstat(path: Path) -> stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _reject_link(path: Path, info: stat_result) -> None:
    if is_link(info):
        message = f'Library path must not be a symbolic link or reparse point: {path}'
        raise LibraryCompatibilityError(message)


def _scanned_directory(path: Path) -> bool:
    info = _optional_lstat(path)
    if info is None:
        return False
    _reject_link(path, info)
    return S_ISDIR(info.st_mode)


def _existing_directory(path: Path) -> bool:
    info = _optional_lstat(path)
    if info is None:
        return False
    _reject_link(path, info)
    if not S_ISDIR(info.st_mode):
        message = f'Library path must be a directory: {path}'
        raise LibraryCompatibilityError(message)
    return True


def _create_directory(path: Path) -> None:
    if _existing_directory(path):
        return
    _create_directory(path.parent)
    path.mkdir(exist_ok=True)
    if not _existing_directory(path):
        message = f'Library directory disappeared: {path}'
        raise LibraryCompatibilityError(message)


def _publish_marker(root: Path) -> None:
    marker = root / LIBRARY_MARKER_PATH
    temporary_path: Path | None = None
    identity: stat_result | None = None
    data = json.dumps({'format_version': LIBRARY_FORMAT_VERSION}).encode() + b'\n'
    try:
        with NamedTemporaryFile(
            mode='wb', dir=marker.parent, prefix='library.', suffix='.tmp', delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            identity = os.fstat(temporary.fileno())
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        _publish_or_validate(root, temporary_path)
    finally:
        if temporary_path is not None and identity is not None:
            _remove_owned_temporary(root, temporary_path, identity)


def _publish_or_validate(root: Path, temporary: Path) -> None:
    if _check_library(root):
        return
    try:
        publish_completed_file(temporary, root / LIBRARY_MARKER_PATH)
    except FileExistsError:
        if not _read_marker(root):
            message = f'Library marker disappeared during initialization: {root}'
            raise LibraryCompatibilityError(message) from None


def _remove_owned_temporary(root: Path, path: Path, identity: stat_result) -> None:
    with suppress(OSError, LibraryCompatibilityError):
        if not _existing_directory(root) or not _existing_directory(path.parent):
            return
        current = path.lstat()
        if not is_link(current) and os.path.samestat(identity, current):
            path.unlink()
