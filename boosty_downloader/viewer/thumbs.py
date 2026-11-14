"""Select post thumbnails from fresh records within the requested author's boundary."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiohttp import web
from yarl import URL

from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.media_thumbnails import iter_cover_candidates
from boosty_downloader.viewer.media import image_file_response
from boosty_downloader.viewer.media_paths import (
    is_author_component,
    resolve_post_folder,
)
from boosty_downloader.viewer.urls import author_relative_path, media_url

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import LibraryReader
    from boosty_downloader.domain.library import LibraryPost
    from boosty_downloader.domain.media_thumbnails import CoverCandidate


def _matches_post(content: LibraryPost, author: str, post_id: str, root: Path) -> bool:
    metadata = content.overview.post
    if metadata.author != author or metadata.id != post_id:
        return False
    record = content.record
    if record is None:
        return content.folder is None
    return (
        record.post.author == author
        and record.post.id == post_id
        and content.folder is not None
        and resolve_post_folder(root, author, content.folder) is not None
    )


def _image_response(
    root: Path, author: str, path: str | None
) -> web.FileResponse | None:
    try:
        relative = author_relative_path(author, path)
    except LibraryReadError:
        return None
    if relative is None:
        return None
    return image_file_response(root, author, relative)


def _candidate_response(
    root: Path, author: str, candidate: CoverCandidate
) -> web.FileResponse | None:
    thumbnail = _image_response(root, author, candidate.thumbnail_path)
    if thumbnail is not None:
        return thumbnail
    if _image_response(root, author, candidate.original_path) is not None:
        relative = author_relative_path(author, candidate.original_path)
        if relative is not None:
            raise web.HTTPFound(location=URL(media_url(author, relative), encoded=True))
    return None


def _thumbnail_response(
    reader: LibraryReader, root: Path, author: str, post_id: str
) -> web.StreamResponse:
    if not is_author_component(author):
        raise web.HTTPNotFound
    detail = reader.post(author, post_id)
    if detail is None or not _matches_post(detail.content, author, post_id, root):
        raise web.HTTPNotFound
    for candidate in iter_cover_candidates(detail.content):
        response = _candidate_response(root, author, candidate)
        if response is not None:
            return response
    raise web.HTTPNotFound


async def serve_thumbnail(
    request: web.Request, *, reader: LibraryReader, library_root: Path
) -> web.StreamResponse:
    """Read the post and inspect its local image candidates in a worker thread."""
    return await asyncio.to_thread(
        _thumbnail_response,
        reader,
        library_root,
        request.match_info['author'],
        request.match_info['post_id'],
    )
