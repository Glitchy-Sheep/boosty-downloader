"""Canonical post-folder ownership and rollback of newly created empty folders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from stat import S_ISDIR
from typing import TYPE_CHECKING, Final
from unicodedata import normalize

from boosty_downloader.domain.post_folder import (
    get_post_id_prefix,
    parse_post_folder_id,
)
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.library._record_paths import (
    resolve_contained_path,
    validate_author_name,
)

if TYPE_CHECKING:
    from types import TracebackType

_POST_FOLDER_DEPTH: Final = 2


def author_directory(root: Path, author: str) -> Path:
    """Keep an author's identity equal to its canonical directory component."""
    validate_author_name(author)
    path = root / author
    directory_exists(path)
    resolved = resolve_contained_path(root, path)
    if resolved != path or _directory_entry_path(resolved) != path:
        message = f'Author folder redirects its identity: {author}'
        raise ValueError(message)
    return path


def canonical_post_folder(root: Path, folder: str, author: str, post_id: str) -> str:
    """Normalize safe aliases within the same author's two-component post layout."""
    _validate_layout(folder, author, post_id)
    path = author_directory(root, author) / PurePosixPath(folder).name
    directory_exists(path)
    resolved = resolve_contained_path(root, path)
    canonical = _directory_entry_path(resolved).relative_to(root).as_posix()
    _validate_layout(canonical, author, post_id)
    return canonical


def _directory_entry_path(path: Path) -> Path:
    """Use actual spelling on case-insensitive and Unicode-normalizing filesystems."""
    if not directory_exists(path):
        return path
    name = portable_path_key(path.name)
    for candidate in path.parent.iterdir():
        if portable_path_key(candidate.name) != name:
            continue
        if not is_link(candidate.lstat()) and candidate.samefile(path):
            return candidate
    message = f'Cannot identify canonical directory entry: {path}'
    raise FileNotFoundError(message)


def portable_path_key(path: str) -> str:
    """Reserve equivalent case and Unicode spellings across supported filesystems."""
    return normalize('NFC', path).casefold()


def _validate_layout(folder: str, author: str, post_id: str) -> None:
    path = PurePosixPath(folder)
    if (
        len(path.parts) != _POST_FOLDER_DEPTH
        or path.as_posix() != folder
        or path.parts[0] != author
        or parse_post_folder_id(path.name) != get_post_id_prefix(post_id)
    ):
        message = f'Invalid folder for {author}/{post_id}: {folder!r}'
        raise ValueError(message)


def directory_exists(path: Path) -> bool:
    """Distinguish absent directories from unreadable, dangling or replaced paths."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if is_link(info):
        info = path.resolve(strict=True).stat()
    if not S_ISDIR(info.st_mode):
        message = f'Post library path is not a directory: {path}'
        raise NotADirectoryError(message)
    return True


def path_is_occupied(path: Path) -> bool:
    """Treat dangling links as occupied folder names."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


@dataclass(frozen=True, slots=True)
class _CreatedDirectory:
    path: Path
    device: int
    inode: int

    def remove_if_owned_and_empty(self) -> None:
        try:
            info = self.path.lstat()
            if info.st_dev == self.device and info.st_ino == self.inode:
                self.path.rmdir()
        except OSError:
            # Existing files and replacement directories belong to their creator.
            pass


class CreatedPostDirectories:
    """Remove only this failed save's unchanged empty directories on rollback."""

    def __init__(self) -> None:
        self._created: list[_CreatedDirectory] = []

    def create(self, path: Path) -> None:
        if directory_exists(path):
            return
        if not directory_exists(path.parent):
            self.create(path.parent)
        try:
            path.mkdir()
        except FileExistsError:
            directory_exists(path)
            return
        info = path.lstat()
        self._created.append(_CreatedDirectory(path, info.st_dev, info.st_ino))

    def __enter__(self) -> CreatedPostDirectories:  # noqa: PYI034 - Python 3.10
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if kind is not None:
            for directory in reversed(self._created):
                directory.remove_if_owned_and_empty()
