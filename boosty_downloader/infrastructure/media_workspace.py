"""Own temporary media outputs without claiming unrelated partial files."""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from os.path import samestat
from pathlib import Path
from shutil import rmtree
from stat import S_ISDIR, S_ISREG
from tempfile import mkdtemp
from typing import TYPE_CHECKING, Final

from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.media_output_paths import (
    create_media_parent,
    resolve_media_destination,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from os import stat_result

_WORKSPACE_PREFIX: Final = '.boosty-'
_WORKSPACE_SUFFIX: Final = '.part'
_OWNER_FILENAME: Final = '.owner'
_OWNER_FORMAT: Final = b'boosty-downloader/media-output/v1\n'
_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class MediaWorkspace:
    """A private output directory beside the reserved final destination."""

    directory: Path
    destination: Path


@contextmanager
def temporary_media_workspace(
    library_root: Path,
    post_folder: str,
    relative_path: str,
    *,
    media_id: str,
) -> Generator[MediaWorkspace, None, None]:
    """
    Create a marked workspace and remove its owned contents on exit.

    The caller persists the final reservation before entry and closes files and stops workers before exit. All files inside this private directory belong to the transfer. Existing workspaces are left alone; cleanup of stopped attempts is explicit.
    """
    marker = _owner_marker(media_id)
    destination = create_media_parent(library_root, post_folder, relative_path)
    directory = Path(
        mkdtemp(
            prefix=_WORKSPACE_PREFIX,
            suffix=_WORKSPACE_SUFFIX,
            dir=destination.parent,
        )
    )
    identity = directory.lstat()
    marker_written = False
    try:
        _write_marker(directory, marker)
        marker_written = True
        yield MediaWorkspace(directory=directory, destination=destination)
    finally:
        _cleanup_current(directory, identity, marker if marker_written else None)


def cleanup_media_workspaces(
    library_root: Path,
    post_folder: str,
    relative_path: str,
    *,
    media_id: str,
) -> None:
    """
    Remove marked workspaces of stopped attempts for this piece and media folder.

    The caller excludes concurrent writers of this piece and waits for the previous worker to stop. A marker proves ownership, not inactivity. Unknown or incomplete markers remain untouched; filesystem errors propagate.
    """
    marker = _owner_marker(media_id)
    destination = resolve_media_destination(library_root, post_folder, relative_path)
    for directory in _workspace_candidates(destination.parent):
        identity = _directory_identity(directory)
        if identity is not None:
            _remove_workspace(directory, identity, marker)


def _owner_marker(media_id: str) -> bytes:
    if not media_id:
        message = 'Temporary media ownership requires a nonempty media ID'
        raise ValueError(message)
    return _OWNER_FORMAT + sha256(media_id.encode('utf-8')).hexdigest().encode() + b'\n'


def _write_marker(directory: Path, marker: bytes) -> None:
    with (directory / _OWNER_FILENAME).open('xb') as file:
        file.write(marker)
        file.flush()
        os.fsync(file.fileno())


def _workspace_candidates(parent: Path) -> list[Path]:
    try:
        return [
            path
            for path in parent.iterdir()
            if path.name.startswith(_WORKSPACE_PREFIX)
            and path.name.endswith(_WORKSPACE_SUFFIX)
        ]
    except FileNotFoundError:
        return []


def _directory_identity(directory: Path) -> stat_result | None:
    try:
        info = directory.lstat()
    except FileNotFoundError:
        return None
    if not S_ISDIR(info.st_mode) or is_link(info):
        return None
    return info


def _has_owner_marker(directory: Path, expected: bytes) -> bool:
    path = directory / _OWNER_FILENAME
    try:
        info = path.lstat()
        if not S_ISREG(info.st_mode) or is_link(info):
            return False
        with path.open('rb') as file:
            return file.read(len(expected) + 1) == expected
    except FileNotFoundError:
        return False


def _remove_workspace(
    directory: Path, identity: stat_result, marker: bytes | None
) -> None:
    current = _directory_identity(directory)
    if current is None or not samestat(current, identity):
        return
    if marker is not None and not _has_owner_marker(directory, marker):
        return
    current = _directory_identity(directory)
    if current is not None and samestat(current, identity):
        _remove_workspace_contents(directory)
        (directory / _OWNER_FILENAME).unlink(missing_ok=True)
        directory.rmdir()


def _remove_workspace_contents(directory: Path) -> None:
    # Retain proof of ownership while any temporary media can remain.
    for path in directory.iterdir():
        if path.name == _OWNER_FILENAME:
            continue
        info = path.lstat()
        if not S_ISDIR(info.st_mode):
            path.unlink()
        elif is_link(info):
            path.rmdir()
        else:
            rmtree(path)


def _cleanup_current(
    directory: Path, identity: stat_result, marker: bytes | None
) -> None:
    try:
        _remove_workspace(directory, identity, marker)
    except OSError as error:
        _logger.warning(
            'Could not remove temporary media directory %s: %s', directory, error
        )
