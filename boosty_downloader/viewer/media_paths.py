"""Resolve library paths within one author's boundary."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath
from typing import Final

_SERVICE_DIRECTORY: Final = '.boosty-downloader'


def is_author_component(author: str) -> bool:
    """Reject path syntax and the library's service directory as an author."""
    if not author or any(char in author for char in '/\\:\x00'):
        return False
    name = author.rstrip(' .').casefold()
    return bool(name) and name != _SERVICE_DIRECTORY


def _relative_parts(relative: str) -> list[str] | None:
    parts = relative.split('/')
    if any(part in {'', '.', '..'} for part in parts):
        return None
    if any(char in relative for char in '\\\x00'):
        return None
    if any(PureWindowsPath(part).drive for part in parts):
        return None
    if any(':' in part for part in parts[:-1]):
        return None
    return parts


def resolve_author_directory(library_root: Path, author: str) -> Path | None:
    """Find a real author directory without accepting a retargeted author alias."""
    if not is_author_component(author):
        return None
    try:
        root = library_root.resolve(strict=True)
        directory = root / author
        resolved = directory.resolve(strict=True)
        if resolved != directory or not resolved.is_dir():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return resolved


def resolve_author_path(library_root: Path, author: str, relative: str) -> Path | None:
    """Resolve an existing path, following only links contained in its author."""
    parts = _relative_parts(relative)
    if parts is None:
        return None
    directory = resolve_author_directory(library_root, author)
    if directory is None:
        return None
    try:
        candidate = directory.joinpath(*parts).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if not candidate.is_relative_to(directory) or candidate == directory:
        return None
    return candidate


def resolve_post_folder(library_root: Path, author: str, folder: str) -> Path | None:
    """Find a real post directory without following folder symlinks."""
    name, separator, relative = folder.partition('/')
    if not separator or name != author:
        return None
    candidate = resolve_author_path(library_root, author, relative)
    if candidate is None:
        return None
    try:
        original = library_root.resolve(strict=True) / folder
        if candidate == original and candidate.is_dir():
            return candidate
    except (OSError, RuntimeError, ValueError):
        return None
    return None


def has_post_folder(library_root: Path, author: str, folder: str) -> bool:
    """Report whether the stored post folder can be opened without redirection."""
    return resolve_post_folder(library_root, author, folder) is not None
