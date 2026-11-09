"""Stat-only inventory of canonical source names for incremental index checks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING

from boosty_downloader.domain.post_folder import parse_post_folder_id
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.library._record_paths import validate_author_name
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_RECORD_FILENAME,
    AUTHOR_SERVICE_FOLDER,
    LOCKED_RECORD_FILENAME,
)
from boosty_downloader.infrastructure.library.index_sources import SourceFingerprint
from boosty_downloader.infrastructure.library.json_store import POST_RECORD_FILENAME
from boosty_downloader.infrastructure.library.post_marks import VIEWER_RECORD_FILENAME

if TYPE_CHECKING:
    from os import stat_result


@dataclass(frozen=True, slots=True)
class PostInventory:
    """A recognized saved folder and the versions of its two owned records."""

    folder: str
    record: SourceFingerprint
    marks: SourceFingerprint | None


@dataclass(frozen=True, slots=True)
class AuthorInventory:
    """Proven canonical sources under one author, without decoded content."""

    author: str
    info: SourceFingerprint | None
    locked: SourceFingerprint | None
    posts: dict[str, PostInventory]


def inventory_sources(root: Path) -> dict[str, AuthorInventory]:
    """Inspect fixed source names, without reading JSON or traversing media."""
    if not _directory(root, root):
        return {}
    authors: dict[str, AuthorInventory] = {}
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.name == AUTHOR_SERVICE_FOLDER:
                continue
            folder = Path(entry.path)
            if not _directory(root, folder, strict=False):
                continue
            source = _author_inventory(root, folder)
            if source.info is not None or source.locked is not None or source.posts:
                validate_author_name(entry.name)
                authors[entry.name] = source
    return authors


def _author_inventory(root: Path, folder: Path) -> AuthorInventory:
    info = locked = None
    service = folder / AUTHOR_SERVICE_FOLDER
    if _directory(root, service):
        info = _fingerprint(root, service / AUTHOR_RECORD_FILENAME)
        locked = _fingerprint(root, service / LOCKED_RECORD_FILENAME)
    posts: dict[str, PostInventory] = {}
    with os.scandir(folder) as entries:
        for entry in entries:
            if parse_post_folder_id(entry.name) is None:
                continue
            post = _post_inventory(root, Path(entry.path))
            if post is not None:
                posts[post.folder] = post
    return AuthorInventory(folder.name, info, locked, posts)


def _post_inventory(root: Path, folder: Path) -> PostInventory | None:
    if not _directory(root, folder, strict=False):
        return None
    record = _fingerprint(root, folder / POST_RECORD_FILENAME)
    if record is None:
        return None
    return PostInventory(
        folder.relative_to(root).as_posix(),
        record,
        _fingerprint(root, folder / VIEWER_RECORD_FILENAME),
    )


def _fingerprint(root: Path, path: Path) -> SourceFingerprint | None:
    info = _source_stat(root, path)
    if info is None:
        return None
    if not S_ISREG(info.st_mode):
        message = f'Library source must be an ordinary file: {path}'
        raise ValueError(message)
    return SourceFingerprint(info.st_mtime_ns, info.st_size)


def _directory(root: Path, path: Path, *, strict: bool = True) -> bool:
    info = _source_stat(root, path)
    if info is None:
        return False
    if S_ISDIR(info.st_mode):
        return True
    if strict:
        message = f'Library source must be a directory: {path}'
        raise NotADirectoryError(message)
    return False


def _source_stat(root: Path, path: Path) -> stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not is_link(info):
        return info
    target = path.resolve(strict=True)
    if not target.is_relative_to(root):
        message = f'Path escapes the library root: {path}'
        raise ValueError(message)
    return target.stat()
