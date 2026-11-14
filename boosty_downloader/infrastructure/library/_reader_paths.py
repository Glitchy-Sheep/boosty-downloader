"""Exact recorded locations for local media and post-folder actions."""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from sqlalchemy import select

from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost
from boosty_downloader.infrastructure.library._record_validation import (
    validate_relative_file_path,
)

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from boosty_downloader.domain.library_media import MediaIdentity


class _MediaLocation(NamedTuple):
    """Recorded file and the owning post's identity and folder."""

    path: str | None
    size: int | None
    folder: str | None
    author: str | None
    post_id: str | None


def read_media_path(
    connection: Connection, author: str, identity: MediaIdentity
) -> str | None:
    """Find one downloaded piece, including retained removed and locked copies."""
    query = (
        select(
            IndexMedia.path,
            IndexMedia.size,
            IndexPost.folder,
            IndexPost.author,
            IndexPost.post_id,
        )
        .outerjoin(IndexPost, IndexPost.id == IndexMedia.post_row_id)
        .where(
            IndexMedia.author == author,
            IndexMedia.post_id == identity.post_id,
            IndexMedia.media_id == identity.media_id,
            IndexMedia.status == MediaStatus.downloaded.value,
        )
    )
    result = connection.execute(query).one_or_none()
    if result is None:
        return None
    return _downloaded_path(_MediaLocation._make(result), author, identity)


def read_post_folder(connection: Connection, author: str, post_id: str) -> str | None:
    """Find the stored folder without requiring current access to its post."""
    query = select(IndexPost.folder).where(
        IndexPost.author == author, IndexPost.post_id == post_id
    )
    folder = connection.execute(query).scalar_one_or_none()
    if folder is not None:
        _validate_folder(folder, author)
    return folder


def _downloaded_path(
    location: _MediaLocation, author: str, identity: MediaIdentity
) -> str:
    if location.author != author or location.post_id != identity.post_id:
        message = 'Indexed media belongs to a different post'
        raise ValueError(message)
    if location.path is None or location.folder is None:
        message = 'Downloaded media requires a recorded file and post folder'
        raise ValueError(message)
    if not isinstance(location.size, int) or location.size < 0:
        message = 'Downloaded media requires a nonnegative integer size'
        raise ValueError(message)
    _validate_folder(location.folder, author)
    _validate_media_path(location.path, location.folder)
    return location.path


def _validate_folder(folder: str, author: str) -> None:
    _validate_path_text(folder, 'indexed post folder')
    folder_author, separator, relative = folder.partition('/')
    if not separator or folder_author != author:
        message = 'Indexed post folder must belong to its author'
        raise ValueError(message)
    validate_relative_file_path(relative, 'author-relative post folder')


def _validate_media_path(path: str, folder: str) -> None:
    _validate_path_text(path, 'indexed media path')
    path_parts = path.split('/')
    folder_parts = folder.split('/')
    if path_parts[: len(folder_parts)] != folder_parts:
        message = 'Indexed media path must belong to its post folder'
        raise ValueError(message)
    relative = '/'.join(path_parts[len(folder_parts) :])
    validate_relative_file_path(relative, 'post-relative media path')


def _validate_path_text(path: object, name: str) -> None:
    if not isinstance(path, str) or not path:
        message = f'{name} must be nonempty text'
        raise ValueError(message)
    validate_relative_file_path(path, name)
