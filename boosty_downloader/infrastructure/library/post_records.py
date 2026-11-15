"""Enumerate, find and save canonical post records within one library root."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING, Final, TypeAlias

from boosty_downloader.domain.library import LocatedPost, SavedPost
from boosty_downloader.domain.post_folder import (
    compose_post_directory_name,
    get_post_id_prefix,
    parse_post_folder_id,
)
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.library._post_json import decode_post_record
from boosty_downloader.infrastructure.library._record_paths import (
    check_containment,
    get_author_folder,
    validate_author_name,
)
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_SERVICE_FOLDER,
)
from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidPostRecordError,
)
from boosty_downloader.infrastructure.library.json_store import (
    POST_RECORD_FILENAME,
    read_post_record,
    write_post_record,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator
    from os import stat_result

    from boosty_downloader.domain.stored_post import PostMetadata, StoredPost

_PostFoldersByPrefix: TypeAlias = dict[str, list[Path]]
_POST_FOLDER_DEPTH: Final = 2


class JsonPostRecords:
    """
    Post-record lookup, folder choice and owned saves for one library run.

    Lookup caches each author's folder paths after a successful scan and reads records afresh. Enumeration always scans the current folders and returns independent records.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._folders_by_author: dict[str, _PostFoldersByPrefix] = {}

    def iter_saved_posts(self, author: str | None = None) -> Iterator[SavedPost]:
        """Read canonical bodies afresh without browsing or viewing metadata."""
        for folder in _saved_author_folders(self._root, author):
            for candidates in _saved_post_groups(self._root, folder).values():
                yield from _read_saved_group(self._root, candidates)

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        """Find the full identity, or one surviving recordless folder, without writes."""
        prefix = get_post_id_prefix(post_id)
        author_folder = get_author_folder(self._root, author)
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

    def choose_post_folder(
        self, post: PostMetadata, *, reserved_folders: Collection[str] = ()
    ) -> str:
        """Suggest a free relative path, excluding reservations, without writes."""
        author_folder = get_author_folder(self._root, post.author)
        collision = 0
        while True:
            name = compose_post_directory_name(
                post.title, post.created_at, post.id, collision=collision
            )
            candidate = author_folder / name
            relative = candidate.relative_to(self._root).as_posix()
            if relative not in reserved_folders and not _is_occupied(candidate):
                check_containment(self._root, candidate)
                return relative
            collision += 1

    def save_post(self, folder: str, record: StoredPost) -> None:
        """Save in a valid owned folder; preserve other posts and retained files."""
        target = self._validated_folder(folder, record.post)
        self._check_ownership(folder, target, record.post)
        prefix = get_post_id_prefix(record.post.id)
        try:
            write_post_record(target, record, create_folder=True)
        except OSError:
            self._remember_failed_folder(target, prefix)
            raise
        self._remember_folder(target, prefix)

    def _validated_folder(self, folder: str, post: PostMetadata) -> Path:
        relative = PurePosixPath(folder)
        prefix = get_post_id_prefix(post.id)
        if (
            len(relative.parts) != _POST_FOLDER_DEPTH
            or relative.as_posix() != folder
            or relative.parts[0] != post.author
            or parse_post_folder_id(relative.name) != prefix
        ):
            msg = f'Invalid folder for {post.author}/{post.id}: {folder!r}'
            raise ValueError(msg)
        target = get_author_folder(self._root, post.author) / relative.name
        check_containment(self._root, target)
        check_containment(self._root, target / POST_RECORD_FILENAME)
        return target

    def _check_ownership(self, folder: str, target: Path, post: PostMetadata) -> None:
        current = self.find_post(post.author, post.id)
        if (
            current is not None
            and current.record is not None
            and current.folder != folder
        ):
            msg = f'Post {post.author}/{post.id} already occupies {current.folder}'
            raise ValueError(msg)
        existing = read_post_record(target)
        if existing is not None and (
            existing.post.author != post.author or existing.post.id != post.id
        ):
            msg = f'Post folder belongs to another post: {folder}'
            raise ValueError(msg)

    def _remember_folder(self, folder: Path, prefix: str) -> None:
        index = self._folders_by_author.setdefault(folder.parent.name, {})
        candidates = index.setdefault(prefix, [])
        if folder not in candidates:
            candidates.append(folder)

    def _remember_failed_folder(self, folder: Path, prefix: str) -> None:
        try:
            if _is_directory(folder):
                self._remember_folder(folder, prefix)
        except OSError:
            # Retry discovery when the failed save's folder cannot be inspected.
            self._folders_by_author.pop(folder.parent.name, None)

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
        check_containment(self._root, folder)
        if not _is_directory(folder):
            return None
        check_containment(self._root, folder / POST_RECORD_FILENAME)
        data = _read_saved_bytes(self._root, folder / POST_RECORD_FILENAME)
        record = None
        if data is not None:
            record = _decode_saved_record(data, folder / POST_RECORD_FILENAME)
        if record is None and not _is_directory(folder):
            return None
        return LocatedPost(folder.relative_to(self._root).as_posix(), record)


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


def _saved_author_folders(root: Path, author: str | None) -> Iterator[Path]:
    if author is not None:
        folder = get_author_folder(root, author)
        if folder.name != AUTHOR_SERVICE_FOLDER and _is_saved_directory(root, folder):
            yield folder
        return
    for folder in _children(root):
        if folder.name != AUTHOR_SERVICE_FOLDER and _is_saved_directory(root, folder):
            yield folder


def _children(folder: Path) -> list[Path]:
    try:
        return sorted(folder.iterdir())
    except FileNotFoundError:
        return []


def _saved_post_groups(root: Path, author: Path) -> _PostFoldersByPrefix:
    folders: _PostFoldersByPrefix = {}
    for folder in _children(author):
        prefix = parse_post_folder_id(folder.name)
        if prefix is not None and _is_saved_directory(root, folder):
            folders.setdefault(prefix, []).append(folder)
    return folders


def _is_saved_directory(root: Path, path: Path) -> bool:
    info = _saved_source_stat(root, path)
    return info is not None and S_ISDIR(info.st_mode)


def _saved_source_stat(root: Path, path: Path) -> stat_result | None:
    check_containment(root, path)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if is_link(info):
        target = _resolved_saved_source(root, path)
        return target.stat()
    return info


def _resolved_saved_source(root: Path, path: Path) -> Path:
    target = path.resolve(strict=True)
    if not target.is_relative_to(root):
        message = f'Path escapes the library root: {path}'
        raise ValueError(message)
    return target


def _read_saved_group(root: Path, folders: list[Path]) -> list[SavedPost]:
    posts: dict[str, SavedPost] = {}
    for folder in folders:
        saved = _read_saved_post(root, folder)
        if saved is None:
            continue
        post_id = saved.record.post.id
        if previous := posts.get(post_id):
            message = (
                f'Multiple post folders for {saved.record.post.author}/{post_id}: '
                f'{previous.folder}, {saved.folder}'
            )
            raise AmbiguousPostFolderError(message)
        posts[post_id] = saved
    return list(posts.values())


def _read_saved_post(root: Path, folder: Path) -> SavedPost | None:
    path = folder / POST_RECORD_FILENAME
    data = _read_saved_bytes(root, path)
    if data is None:
        return None
    validate_author_name(folder.parent.name)
    record = _decode_saved_record(data, path)
    if record.post.author != folder.parent.name or get_post_id_prefix(
        record.post.id
    ) != parse_post_folder_id(folder.name):
        message = f'Post record does not match its author and folder: {folder}'
        raise InvalidPostRecordError(message)
    return SavedPost(folder.relative_to(root).as_posix(), record)


def _decode_saved_record(data: bytes, path: Path) -> StoredPost:
    try:
        return decode_post_record(data)
    except InvalidPostRecordError as error:
        message = f'{path}: {error}'
        raise type(error)(message) from error


def _read_saved_bytes(root: Path, path: Path) -> bytes | None:
    expected = _saved_source_stat(root, path)
    if expected is None:
        return None
    if not S_ISREG(expected.st_mode):
        message = f'Post record must be an ordinary file: {path}'
        raise InvalidPostRecordError(message)
    target = _resolved_saved_source(root, path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(target, flags)
    with os.fdopen(descriptor, 'rb') as source:
        actual = os.fstat(source.fileno())
        if not S_ISREG(actual.st_mode) or not os.path.samestat(expected, actual):
            message = f'Post record changed while being read: {path}'
            raise OSError(message)
        return source.read()
