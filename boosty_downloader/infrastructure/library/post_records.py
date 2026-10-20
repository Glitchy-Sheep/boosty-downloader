"""Find stable post folders and choose unused paths within one library root."""

from __future__ import annotations

import re
from pathlib import Path, PureWindowsPath
from stat import S_ISDIR
from typing import TYPE_CHECKING, TypeAlias

from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.post_folder import (
    compose_post_directory_name,
    get_post_id_prefix,
    parse_post_folder_id,
)
from boosty_downloader.infrastructure.library.errors import AmbiguousPostFolderError
from boosty_downloader.infrastructure.library.json_store import (
    POST_RECORD_FILENAME,
    read_post_record,
)

if TYPE_CHECKING:
    from boosty_downloader.domain.stored_post import PostMetadata

_PostFoldersByPrefix: TypeAlias = dict[str, list[Path]]
_UNSAFE_AUTHOR_CHARACTERS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


class JsonPostRecords:
    """
    Post-record lookup and folder choice for one library run.

    Each author's folders are indexed once after a successful scan. Only paths are cached; records are read afresh. A new instance discovers folders added or renamed outside this component.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._folders_by_author: dict[str, _PostFoldersByPrefix] = {}

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        """Find the full identity, or one surviving recordless folder, without writes."""
        prefix = get_post_id_prefix(post_id)
        author_folder = self._author_folder(author)
        candidates = self._read_candidates(author_folder, prefix)
        matches = [
            candidate
            for candidate in candidates
            if candidate.record is not None
            and candidate.record.post.author == author
            and candidate.record.post.id == post_id
        ]
        if not matches:
            matches = [
                candidate for candidate in candidates if candidate.record is None
            ]
        return _unique_post(matches, author, post_id)

    def choose_post_folder(self, post: PostMetadata) -> str:
        """Suggest an unoccupied relative path without creating or reserving it."""
        author_folder = self._author_folder(post.author)
        collision = 0
        while True:
            name = compose_post_directory_name(
                post.title, post.created_at, post.id, collision=collision
            )
            candidate = author_folder / name
            if not _is_occupied(candidate):
                self._check_containment(candidate)
                return candidate.relative_to(self._root).as_posix()
            collision += 1

    def _author_folder(self, author: str) -> Path:
        _validate_author(author)
        folder = self._root / author
        self._check_containment(folder)
        try:
            mode = folder.stat().st_mode
        except FileNotFoundError:
            return folder
        if not S_ISDIR(mode):
            msg = f'Author folder is not a directory: {folder}'
            raise NotADirectoryError(msg)
        return folder

    def _check_containment(self, path: Path) -> None:
        if not path.resolve().is_relative_to(self._root):
            msg = f'Path escapes the library root: {path}'
            raise ValueError(msg)

    def _folders_for(self, author_folder: Path) -> _PostFoldersByPrefix:
        author = author_folder.name
        if author not in self._folders_by_author:
            self._folders_by_author[author] = _scan_post_folders(author_folder)
        return self._folders_by_author[author]

    def _read_candidates(self, author_folder: Path, prefix: str) -> list[LocatedPost]:
        candidates: list[LocatedPost] = []
        for folder in self._folders_for(author_folder).get(prefix, []):
            located = self._read_folder(folder)
            if located is not None:
                candidates.append(located)
        return candidates

    def _read_folder(self, folder: Path) -> LocatedPost | None:
        self._check_containment(folder)
        if not _is_directory(folder):
            return None
        self._check_containment(folder / POST_RECORD_FILENAME)
        record = read_post_record(folder)
        if record is None and not _is_directory(folder):
            return None
        return LocatedPost(folder.relative_to(self._root).as_posix(), record)


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


def _scan_post_folders(author_folder: Path) -> _PostFoldersByPrefix:
    folders: _PostFoldersByPrefix = {}
    try:
        children = list(author_folder.iterdir())
    except FileNotFoundError:
        return folders
    for child in children:
        prefix = parse_post_folder_id(child.name)
        if prefix is not None and _is_directory(child):
            folders.setdefault(prefix, []).append(child)
    return folders


def _is_directory(path: Path) -> bool:
    try:
        return S_ISDIR(path.stat().st_mode)
    except FileNotFoundError:
        return False


def _is_occupied(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _unique_post(
    candidates: list[LocatedPost], author: str, post_id: str
) -> LocatedPost | None:
    if not candidates:
        return None
    if len(candidates) > 1:
        paths = ', '.join(sorted(candidate.folder for candidate in candidates))
        msg = f'Multiple post folders for {author}/{post_id}: {paths}'
        raise AmbiguousPostFolderError(msg)
    return candidates[0]
