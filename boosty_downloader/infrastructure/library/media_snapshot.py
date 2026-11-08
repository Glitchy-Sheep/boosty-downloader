"""Read post-relative file observations without changing the library."""

from __future__ import annotations

from os import scandir, stat_result
from os.path import samestat
from pathlib import Path, PurePosixPath
from stat import FILE_ATTRIBUTE_REPARSE_POINT, S_ISDIR, S_ISLNK, S_ISREG
from typing import TYPE_CHECKING
from unicodedata import normalize

from boosty_downloader.domain.disk_snapshot import DiskSnapshot
from boosty_downloader.infrastructure.library._record_paths import check_containment
from boosty_downloader.infrastructure.library._record_validation import (
    validate_relative_file_path,
)

if TYPE_CHECKING:
    from collections.abc import Collection


def read_media_snapshot(
    library_root: Path,
    post_folder: str,
    *,
    queried_paths: Collection[str] = (),
) -> DiskSnapshot:
    """
    Observe one post's tree, including empty files and occupied non-file names.

    Directory links are not traversed. Missing folders stay absent; other I/O errors propagate. Temporary files are observed too, but reconciliation excludes them from recovery.
    """
    folder = _resolve_post_folder(library_root, post_folder)
    files: dict[str, int] = {}
    occupied: set[str] = set()
    _scan_directory(folder, folder, files, occupied)
    disk = DiskSnapshot(files=files, occupied=frozenset(occupied))
    if queried_paths:
        return confirm_media_aliases(library_root, post_folder, disk, queried_paths)
    return disk


def confirm_media_aliases(
    library_root: Path,
    post_folder: str,
    disk: DiskSnapshot,
    queried_paths: Collection[str],
) -> DiskSnapshot:
    """
    Confirm concrete case/Unicode spellings without rescanning directories.

    The caller supplies complete filenames, including any discovered suffix or collision marker. Filesystem identity, not normalized spelling, proves each alias. The input snapshot is unchanged.
    """
    folder = _resolve_post_folder(library_root, post_folder)
    candidates = _alias_candidates(disk)
    aliases = dict(disk.aliases)
    for queried in sorted(set(queried_paths)):
        aliases.pop(queried, None)
        observed = _confirmed_alias(folder, queried, candidates)
        if observed is not None and observed != queried:
            aliases[queried] = observed
    return DiskSnapshot(dict(disk.files), frozenset(disk.occupied), aliases)


def _resolve_post_folder(library_root: Path, post_folder: str) -> Path:
    validate_relative_file_path(post_folder, 'post folder')
    root = library_root.resolve()
    folder = root / post_folder
    check_containment(root, folder)
    return folder.resolve()


def _stat_if_present(path: Path) -> stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _is_link(info: stat_result) -> bool:
    attributes = getattr(info, 'st_file_attributes', 0)
    return S_ISLNK(info.st_mode) or bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)


def _scan_directory(
    root: Path, folder: Path, files: dict[str, int], occupied: set[str]
) -> None:
    info = _stat_if_present(folder)
    if info is None or _is_link(info):
        return
    if not S_ISDIR(info.st_mode):
        raise NotADirectoryError(str(folder))
    check_containment(root, folder)
    with scandir(folder) as entries:
        paths = sorted(Path(entry.path) for entry in entries)
    for path in paths:
        _observe_entry(root, path, files, occupied)


def _observe_entry(
    root: Path, path: Path, files: dict[str, int], occupied: set[str]
) -> None:
    info = _stat_if_present(path)
    if info is None:
        return
    relative = path.relative_to(root).as_posix()
    if S_ISREG(info.st_mode) and not _is_link(info):
        files[relative] = info.st_size
        return
    occupied.add(relative)
    if S_ISDIR(info.st_mode) and not _is_link(info):
        _scan_directory(root, path, files, occupied)


def _alias_candidates(disk: DiskSnapshot) -> dict[str, list[str]]:
    candidates: dict[str, list[str]] = {}
    for path in sorted(disk.files):
        candidates.setdefault(_spelling_key(path), []).append(path)
    return candidates


def _spelling_key(path: str) -> str:
    return normalize('NFC', path).casefold()


def _confirmed_alias(
    folder: Path, queried: str, candidates: dict[str, list[str]]
) -> str | None:
    info = _query_file_stat(folder, queried)
    if info is None:
        return None
    matches = candidates.get(_spelling_key(queried), [])
    if queried in matches:
        return queried
    for candidate in matches:
        actual = _query_file_stat(folder, candidate)
        if actual is not None and samestat(info, actual):
            return candidate
    return None


def _query_file_stat(folder: Path, relative: str) -> stat_result | None:
    validate_relative_file_path(relative, 'media path')
    parent = folder
    for part in PurePosixPath(relative).parts[:-1]:
        parent /= part
        info = _stat_if_present(parent)
        if info is None:
            return None
        if _is_link(info):
            message = f'Media path traverses a directory link: {relative}'
            raise ValueError(message)
        if not S_ISDIR(info.st_mode):
            raise NotADirectoryError(str(parent))
    info = _stat_if_present(folder / relative)
    if info is None or _is_link(info) or not S_ISREG(info.st_mode):
        return None
    return info
