"""Validate reserved media paths and create their ordinary parent directories."""

import errno
from pathlib import Path, PurePosixPath
from stat import S_ISDIR
from unicodedata import normalize

from boosty_downloader.infrastructure.library._media_paths import (
    is_link,
    resolve_post_folder,
)
from boosty_downloader.infrastructure.library._record_validation import (
    validate_relative_file_path,
)
from boosty_downloader.infrastructure.path_sanitizer import sanitize_filename


def resolve_media_destination(
    library_root: Path, post_folder: str, relative_path: str
) -> Path:
    """Locate reserved media without creating folders or following the final entry."""
    _validate_portable_path(post_folder, 'post folder')
    _validate_portable_path(relative_path, 'media path')
    folder = resolve_post_folder(library_root, post_folder)
    _directory_exists(folder)
    parent = folder
    for component in PurePosixPath(relative_path).parts[:-1]:
        parent /= component
        _directory_exists(parent)
    return folder / relative_path


def create_media_parent(
    library_root: Path, post_folder: str, relative_path: str
) -> Path:
    """Create a reserved destination's parents, rejecting every occupied final entry."""
    destination = resolve_media_destination(library_root, post_folder, relative_path)
    _require_absent(destination)
    _create_directory(destination.parent)
    destination = resolve_media_destination(library_root, post_folder, relative_path)
    _require_absent(destination)
    return destination


def _validate_portable_path(value: str, name: str) -> None:
    validate_relative_file_path(value, name)
    for component in value.split('/'):
        normalized = normalize('NFC', component)
        cleaned = sanitize_filename(
            normalized, max_bytes=len(normalized.encode('utf-8'))
        )
        if cleaned != normalized:
            message = f'{name} contains a non-portable filename: {component!r}'
            raise ValueError(message)


def _directory_exists(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if is_link(info):
        message = f'Media path traverses a directory link: {path}'
        raise ValueError(message)
    if not S_ISDIR(info.st_mode):
        raise NotADirectoryError(errno.ENOTDIR, 'Media parent is not a directory', path)
    return True


def _create_directory(path: Path) -> None:
    if _directory_exists(path):
        return
    _create_directory(path.parent)
    path.mkdir(exist_ok=True)
    if not _directory_exists(path):
        raise FileNotFoundError(errno.ENOENT, 'Media parent no longer exists', path)


def _require_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise FileExistsError(errno.EEXIST, 'Media destination is occupied', path)
