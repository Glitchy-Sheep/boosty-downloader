"""Read and atomically save author details and locked-post observations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from boosty_downloader.infrastructure.library._atomic_write import write_atomically
from boosty_downloader.infrastructure.library._author_json import (
    decode_author_record,
    decode_locked_posts,
    encode_author_record,
    encode_locked_posts,
)
from boosty_downloader.infrastructure.library._record_paths import (
    check_containment,
    get_author_folder,
)
from boosty_downloader.infrastructure.library.errors import InvalidAuthorRecordError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from boosty_downloader.domain.stored_post import AuthorInfo, LockedPost

AUTHOR_SERVICE_FOLDER: Final = '.boosty-downloader'
AUTHOR_RECORD_FILENAME: Final = 'author.json'
LOCKED_RECORD_FILENAME: Final = 'locked.json'


def read_author_record(root: Path, author: str) -> AuthorInfo | None:
    """Read an owned author snapshot; a missing file returns None without writes."""
    path = _record_path(root, author, AUTHOR_RECORD_FILENAME)
    data = _read_optional(path)
    if data is None:
        return None
    try:
        info = decode_author_record(data)
    except InvalidAuthorRecordError as error:
        message = f'{path}: {error}'
        raise type(error)(message) from error
    if info.author != author:
        message = f'{path}: Author record belongs to another author'
        raise InvalidAuthorRecordError(message)
    return info


def read_locked_posts(root: Path, author: str) -> dict[str, LockedPost]:
    """Read fresh owned observations; a missing file returns an empty mapping."""
    path = _record_path(root, author, LOCKED_RECORD_FILENAME)
    data = _read_optional(path)
    if data is None:
        return {}
    try:
        return decode_locked_posts(data, author=author)
    except InvalidAuthorRecordError as error:
        message = f'{path}: {error}'
        raise type(error)(message) from error


def write_author_record(root: Path, info: AuthorInfo) -> None:
    """Replace a supported, owned author snapshot without changing other files."""
    path = _record_path(root, info.author, AUTHOR_RECORD_FILENAME)
    read_author_record(root, info.author)
    try:
        data = encode_author_record(info)
    except InvalidAuthorRecordError as error:
        message = f'{path}: {error}'
        raise type(error)(message) from error
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(path, data)


def save_locked_post(root: Path, post: LockedPost) -> None:
    """Upsert one full-ID observation without creating or changing post folders."""
    author = post.post.author
    path = _record_path(root, author, LOCKED_RECORD_FILENAME)
    posts = read_locked_posts(root, author)
    posts[post.post.id] = post
    _write_locked_posts(path, author, posts)


def clear_locked_post(root: Path, author: str, post_id: str) -> None:
    """Clear one observation; missing IDs cause no writes or directory creation."""
    path = _record_path(root, author, LOCKED_RECORD_FILENAME)
    posts = read_locked_posts(root, author)
    if post_id not in posts:
        return
    del posts[post_id]
    _write_locked_posts(path, author, posts)


def _record_path(root: Path, author: str, filename: str) -> Path:
    root = root.resolve()
    folder = get_author_folder(root, author) / AUTHOR_SERVICE_FOLDER
    check_containment(root, folder)
    path = folder / filename
    check_containment(root, path)
    return path


def _read_optional(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _write_locked_posts(
    path: Path, author: str, posts: Mapping[str, LockedPost]
) -> None:
    try:
        data = encode_locked_posts(author, posts)
    except InvalidAuthorRecordError as error:
        message = f'{path}: {error}'
        raise type(error)(message) from error
    path.parent.mkdir(parents=True, exist_ok=True)
    write_atomically(path, data)
