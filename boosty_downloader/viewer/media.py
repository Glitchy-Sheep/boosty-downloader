"""Serve exact library files with an explicit browser execution policy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from stat import S_ISREG
from typing import TYPE_CHECKING, Final, TypeAlias

from aiohttp import web

from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.viewer.file_types import suffix
from boosty_downloader.viewer.media_paths import (
    is_author_component,
    resolve_author_path,
)

if TYPE_CHECKING:
    from os import stat_result
    from pathlib import Path

    from boosty_downloader.application.ports import LibraryReader

FileStatSelection: TypeAlias = tuple['Path | None', 'stat_result', str | None]
_SAVED_PAGE: Final = 'post.html'
_SAVED_PAGE_POLICY: Final = (
    "default-src 'self'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; media-src 'self'; frame-ancestors 'self'; "
    'sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox'
)
_INERT_POLICY: Final = (
    "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
)
_INLINE_TYPES: Final = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.gif': 'image/gif',
    '.webp': 'image/webp',
    '.avif': 'image/avif',
    '.bmp': 'image/bmp',
    '.mp3': 'audio/mpeg',
    '.m4a': 'audio/mp4',
    '.aac': 'audio/aac',
    '.ogg': 'audio/ogg',
    '.oga': 'audio/ogg',
    '.opus': 'audio/ogg',
    '.wav': 'audio/wav',
    '.flac': 'audio/flac',
    '.mp4': 'video/mp4',
    '.m4v': 'video/mp4',
    '.webm': 'video/webm',
    '.mov': 'video/quicktime',
    '.mkv': 'video/x-matroska',
    '.pdf': 'application/pdf',
    '.txt': 'text/plain; charset=utf-8',
    '.md': 'text/plain; charset=utf-8',
    '.csv': 'text/plain; charset=utf-8',
    '.vtt': 'text/vtt; charset=utf-8',
}


@dataclass(frozen=True, slots=True)
class _MediaFile:
    path: Path
    headers: dict[str, str]


class _ExactFile(web.FileResponse):
    """Keep native Range support without selecting compressed sibling files."""

    def _get_file_path_stat_encoding(self, accept_encoding: str) -> FileStatSelection:
        del accept_encoding
        return super()._get_file_path_stat_encoding('')


def _saved_page_matches(
    reader: LibraryReader, root: Path, author: str, relative: str, path: Path
) -> bool:
    if relative.rsplit('/', 1)[-1] != _SAVED_PAGE or path.name != _SAVED_PAGE:
        return False
    try:
        page = reader.saved_page(author, relative)
    except LibraryReadError:
        return False
    if page is None or page.path != f'{author}/{relative}':
        return False
    if page.path != f'{page.folder}/{_SAVED_PAGE}':
        return False
    name, separator, confirmed = page.path.partition('/')
    if not separator or name != author:
        return False
    return resolve_author_path(root, author, confirmed) == path


def _headers(content_type: str, *, saved_page: bool = False) -> dict[str, str]:
    headers = {
        'Content-Type': content_type,
        'X-Content-Type-Options': 'nosniff',
        'Cross-Origin-Resource-Policy': 'same-origin',
        'Referrer-Policy': 'no-referrer',
    }
    if saved_page:
        headers['Content-Security-Policy'] = _SAVED_PAGE_POLICY
    elif content_type == 'application/octet-stream':
        headers['Content-Disposition'] = 'attachment'
        headers['Content-Security-Policy'] = _INERT_POLICY
    return headers


def _select_media(
    reader: LibraryReader, root: Path, author: str, relative: str
) -> _MediaFile:
    if not is_author_component(author) or not reader.has_author(author):
        raise web.HTTPNotFound
    path = resolve_author_path(root, author, relative)
    try:
        if path is None or not S_ISREG(path.stat().st_mode):
            raise web.HTTPNotFound
    except OSError as error:
        raise web.HTTPNotFound from error
    if _saved_page_matches(reader, root, author, relative, path):
        return _MediaFile(path, _headers('text/html; charset=utf-8', saved_page=True))
    content_type = None if ':' in relative else _INLINE_TYPES.get(suffix(path.name))
    return _MediaFile(path, _headers(content_type or 'application/octet-stream'))


async def serve_media(
    request: web.Request, *, reader: LibraryReader, library_root: Path
) -> web.StreamResponse:
    """Serve a listed author's exact local file without blocking the event loop."""
    media = await asyncio.to_thread(
        _select_media,
        reader,
        library_root,
        request.match_info['author'],
        request.match_info['path'],
    )
    return _ExactFile(media.path, headers=media.headers)
