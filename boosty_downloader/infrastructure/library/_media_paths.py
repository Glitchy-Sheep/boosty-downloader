"""Shared containment and link checks for post media."""

from os import stat_result
from pathlib import Path
from stat import FILE_ATTRIBUTE_REPARSE_POINT, S_ISLNK

from boosty_downloader.infrastructure.library._record_paths import (
    resolve_contained_path,
)
from boosty_downloader.infrastructure.library._record_validation import (
    validate_relative_file_path,
)


def resolve_post_folder(library_root: Path, post_folder: str) -> Path:
    """Resolve a post folder, allowing links only within the library."""
    validate_relative_file_path(post_folder, 'post folder')
    root = library_root.resolve()
    folder = root / post_folder
    return resolve_contained_path(root, folder)


def is_link(info: stat_result) -> bool:
    """Recognize symbolic links and Windows reparse points."""
    attributes = getattr(info, 'st_file_attributes', 0)
    return S_ISLNK(info.st_mode) or bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)
