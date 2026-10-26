"""Author directory and containment checks for library records."""

import re
from pathlib import Path, PureWindowsPath
from stat import S_ISDIR

_UNSAFE_AUTHOR_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


def get_author_folder(root: Path, author: str) -> Path:
    """Locate an author under a resolved library root without creating folders."""
    _validate_author(author)
    folder = root / author
    check_containment(root, folder)
    try:
        mode = folder.stat().st_mode
    except FileNotFoundError:
        return folder
    if not S_ISDIR(mode):
        msg = f'Author folder is not a directory: {folder}'
        raise NotADirectoryError(msg)
    return folder


def check_containment(root: Path, path: Path) -> None:
    """Reject paths that resolve outside an already resolved library root."""
    if not path.resolve().is_relative_to(root):
        msg = f'Path escapes the library root: {path}'
        raise ValueError(msg)


def _validate_author(author: str) -> None:
    if (
        not author
        or author in {'.', '..'}
        or author != author.strip()
        or author.endswith('.')
        or _UNSAFE_AUTHOR_CHARACTERS.search(author)
        or PureWindowsPath(author).is_reserved()
    ):
        msg = f'Author must be a single portable directory name: {author!r}'
        raise ValueError(msg)
