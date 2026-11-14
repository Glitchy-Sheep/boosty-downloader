"""Resolve a saved post link without requiring the disposable browsing index."""

from __future__ import annotations

from collections.abc import Callable
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING, Final, TypeAlias

from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.media_output_paths import (
    resolve_media_destination,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.domain.library import LocatedPost

FindPostRecord: TypeAlias = Callable[[str, str], 'LocatedPost | None']
_POST_FOLDER_DEPTH: Final = 2


class SavedPageLinkResolver:
    """Link only to an owned regular page with a matching canonical record."""

    def __init__(self, root: Path, find_post: FindPostRecord) -> None:
        self._root = root
        self._find_post = find_post

    def post_folder(self, author: str, post_id: str) -> str | None:
        """Leave missing, corrupt or redirected optional targets on Boosty."""
        try:
            located = self._find_post(author, post_id)
            if located is None or not _matches_post(located, author, post_id):
                return None
            if is_linkable_page_folder(self._root, located.folder):
                return located.folder
        except (OSError, ValueError):
            return None
        return None


def _matches_post(located: LocatedPost, author: str, post_id: str) -> bool:
    if located.record is None:
        return False
    post = located.record.post
    folder_parts = located.folder.split('/')
    return (
        post.author == author
        and post.id == post_id
        and len(folder_parts) == _POST_FOLDER_DEPTH
        and folder_parts[0] == author
    )


def is_linkable_page_folder(
    root: Path, folder: str, *, allow_missing: bool = False
) -> bool:
    """Accept ordinary library page paths, optionally before their publication."""
    if len(folder.split('/')) != _POST_FOLDER_DEPTH:
        return False
    try:
        path = resolve_media_destination(root, folder, 'post.html')
        if not _ordinary_folders(root, folder, allow_missing=allow_missing):
            return False
        try:
            info = path.lstat()
        except FileNotFoundError:
            return allow_missing
        return S_ISREG(info.st_mode) and not is_link(info)
    except (OSError, ValueError):
        return False


def _ordinary_folders(root: Path, folder: str, *, allow_missing: bool) -> bool:
    current = root.resolve()
    for component in folder.split('/'):
        current /= component
        try:
            info = current.lstat()
        except FileNotFoundError:
            return allow_missing
        if is_link(info) or not S_ISDIR(info.st_mode):
            return False
    return True
