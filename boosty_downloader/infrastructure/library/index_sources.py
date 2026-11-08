"""Validated canonical records and file fingerprints for index projection."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING

from boosty_downloader.domain.library import LibraryPost, PostAccess, PostOverview
from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.domain.post_folder import (
    get_post_id_prefix,
    parse_post_folder_id,
)
from boosty_downloader.domain.stored_post import LockedPost
from boosty_downloader.infrastructure.library._author_json import (
    decode_author_record,
    decode_locked_posts,
)
from boosty_downloader.infrastructure.library._index_cover import find_cover_path
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.library._post_json import decode_post_record
from boosty_downloader.infrastructure.library._record_paths import (
    check_containment,
    validate_author_name,
)
from boosty_downloader.infrastructure.library._viewer_json import decode_viewer_record
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_RECORD_FILENAME,
    AUTHOR_SERVICE_FOLDER,
    LOCKED_RECORD_FILENAME,
)
from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidAuthorRecordError,
    InvalidPostRecordError,
)
from boosty_downloader.infrastructure.library.json_store import POST_RECORD_FILENAME
from boosty_downloader.infrastructure.library.post_marks import VIEWER_RECORD_FILENAME

if TYPE_CHECKING:
    from collections.abc import Iterator
    from os import stat_result
    from pathlib import Path

    from boosty_downloader.domain.stored_post import AuthorInfo, StoredPost


@dataclass(frozen=True, slots=True)
class SourceFingerprint:
    """The modification time in nanoseconds and byte length of one source file."""

    mtime_ns: int
    size: int


@dataclass(frozen=True, slots=True)
class AuthorSource:
    """One author's display information and independent access observations."""

    author: str
    info: AuthorInfo | None = None
    locked_posts: dict[str, LockedPost] = field(default_factory=dict[str, LockedPost])
    author_fingerprint: SourceFingerprint | None = None
    locked_fingerprint: SourceFingerprint | None = None


@dataclass(frozen=True, slots=True)
class PostSource:
    """A complete post snapshot; cover paths are relative to the library root."""

    post: LibraryPost
    marks: PostMarks = field(default_factory=PostMarks)
    record_fingerprint: SourceFingerprint | None = None
    marks_fingerprint: SourceFingerprint | None = None
    cover_path: str | None = None


@dataclass(frozen=True, slots=True)
class _SourceFile:
    data: bytes
    fingerprint: SourceFingerprint


def scan_authors(root: Path) -> Iterator[AuthorSource]:
    """Read proven author folders once, without creating files or opening old caches."""
    root = root.resolve()
    if not _source_directory(root, root):
        return
    for folder in sorted(root.iterdir()):
        if folder.name == AUTHOR_SERVICE_FOLDER or not _ordinary_directory(
            root, folder
        ):
            continue
        source = _read_author(root, folder)
        if (
            source.author_fingerprint
            or source.locked_fingerprint
            or _has_records(root, folder)
        ):
            validate_author_name(folder.name)
            yield source


def _read_author(root: Path, folder: Path) -> AuthorSource:
    service = folder / AUTHOR_SERVICE_FOLDER
    if not _source_directory(root, service):
        return AuthorSource(folder.name)
    author = _read_source(root, service / AUTHOR_RECORD_FILENAME)
    locked = _read_source(root, service / LOCKED_RECORD_FILENAME)
    info = decode_author_record(author.data) if author is not None else None
    if info is not None and info.author != folder.name:
        message = f'Author record belongs to another author: {service}'
        raise InvalidAuthorRecordError(message)
    return AuthorSource(
        author=folder.name,
        info=info,
        locked_posts=decode_locked_posts(locked.data, author=folder.name)
        if locked
        else {},
        author_fingerprint=author.fingerprint if author else None,
        locked_fingerprint=locked.fingerprint if locked else None,
    )


def _has_records(root: Path, folder: Path) -> bool:
    return any(
        _optional_lstat(post / POST_RECORD_FILENAME) is not None
        for post in _post_folders(root, folder)
    )


def _post_folders(root: Path, author_folder: Path) -> Iterator[Path]:
    if not _source_directory(root, author_folder):
        return
    for folder in sorted(author_folder.iterdir()):
        if parse_post_folder_id(folder.name) is not None and _ordinary_directory(
            root, folder
        ):
            yield folder


def scan_posts(root: Path, author: AuthorSource) -> Iterator[PostSource]:
    """Stream independent records with newer access observations and saved marks."""
    root = root.resolve()
    validate_author_name(author.author)
    remaining_locked = dict(author.locked_posts)
    seen: set[str] = set()
    for folder in _post_folders(root, root / author.author):
        source = _read_post(root, folder, remaining_locked)
        if source is None:
            continue
        post_id = source.post.overview.post.id
        if post_id in seen:
            message = f'Multiple post folders for {author.author}/{post_id}'
            raise AmbiguousPostFolderError(message)
        seen.add(post_id)
        yield source
    for locked in remaining_locked.values():
        post = LibraryPost(
            PostOverview(deepcopy(locked.post), PostAccess.locked),
            teaser_path=locked.teaser_path,
        )
        yield PostSource(post=post, cover_path=find_cover_path(root, post))


def _read_post(
    root: Path, folder: Path, locked: dict[str, LockedPost]
) -> PostSource | None:
    source = _read_source(root, folder / POST_RECORD_FILENAME)
    if source is None:
        return None
    record = decode_post_record(source.data)
    _validate_post_folder(folder, record)
    observation = locked.pop(record.post.id, None)
    post = _library_post(root, folder, record, observation)
    marks = _read_source(root, folder / VIEWER_RECORD_FILENAME)
    return PostSource(
        post=post,
        marks=_decode_marks(marks, record),
        record_fingerprint=source.fingerprint,
        marks_fingerprint=marks.fingerprint if marks else None,
        cover_path=find_cover_path(root, post),
    )


def _validate_post_folder(folder: Path, record: StoredPost) -> None:
    if record.post.author != folder.parent.name or parse_post_folder_id(
        folder.name
    ) != get_post_id_prefix(record.post.id):
        message = f'Post record does not match its author and folder: {folder}'
        raise InvalidPostRecordError(message)


def _library_post(
    root: Path, folder: Path, record: StoredPost, locked: LockedPost | None
) -> LibraryPost:
    metadata = deepcopy(locked.post) if locked is not None else record.post
    access = PostAccess.locked if locked is not None else PostAccess.open
    return LibraryPost(
        overview=PostOverview(metadata, access),
        record=record,
        folder=folder.relative_to(root).as_posix(),
        teaser_path=locked.teaser_path if locked is not None else None,
    )


def _decode_marks(source: _SourceFile | None, record: StoredPost) -> PostMarks:
    if source is None:
        return PostMarks()
    return decode_viewer_record(
        source.data, author=record.post.author, post_id=record.post.id
    )


def _optional_lstat(path: Path) -> stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _ordinary_directory(root: Path, path: Path) -> bool:
    info = _source_stat(root, path)
    if info is None:
        return False
    return S_ISDIR(info.st_mode)


def _source_stat(root: Path, path: Path) -> stat_result | None:
    check_containment(root, path)
    info = _optional_lstat(path)
    if info is not None and is_link(info):
        return path.resolve(strict=True).stat()
    return info


def _read_source(root: Path, path: Path) -> _SourceFile | None:
    expected = _source_stat(root, path)
    if expected is None:
        return None
    if not S_ISREG(expected.st_mode):
        message = f'Library source must be an ordinary file: {path}'
        raise ValueError(message)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path.resolve(strict=True), flags)
    with os.fdopen(descriptor, 'rb') as source:
        actual = os.fstat(source.fileno())
        if not S_ISREG(actual.st_mode) or not os.path.samestat(expected, actual):
            message = f'Library source changed while being read: {path}'
            raise OSError(message)
        return _SourceFile(
            source.read(), SourceFingerprint(actual.st_mtime_ns, actual.st_size)
        )


def _source_directory(root: Path, path: Path) -> bool:
    info = _source_stat(root, path)
    if info is None:
        return False
    if not S_ISDIR(info.st_mode):
        message = f'Library source must be a directory: {path}'
        raise NotADirectoryError(message)
    return True
