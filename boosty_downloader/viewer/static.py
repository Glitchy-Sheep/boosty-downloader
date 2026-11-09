"""Serve the packaged application and its negotiated compressed assets."""

from __future__ import annotations

import asyncio
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from typing import TYPE_CHECKING, Final, TypeAlias

from aiohttp import web

from boosty_downloader.viewer.compression import ContentEncoding, select_encoding
from boosty_downloader.viewer.pages import LibraryNotice, notice_page

if TYPE_CHECKING:
    from os import stat_result

FileSelection: TypeAlias = tuple[Path | None, 'stat_result', str | None]
_COMPRESSED_SUFFIXES: Final = {
    ContentEncoding.brotli: '.br',
    ContentEncoding.gzip: '.gz',
}
_ENCODING_PRIORITY: Final = (
    ContentEncoding.brotli,
    ContentEncoding.gzip,
    ContentEncoding.identity,
)
_MISSING_BUILD: Final = LibraryNotice(
    'Viewer UI is not built',
    'Run task ui:build in the project, then restart the viewer.',
)


@dataclass(frozen=True, slots=True)
class _Asset:
    path: Path
    content_type: str
    encoding: ContentEncoding
    cache_control: str


class _SelectedFile(web.FileResponse):
    """Serve the chosen representation without a second encoding negotiation."""

    def _get_file_path_stat_encoding(self, accept_encoding: str) -> FileSelection:
        del accept_encoding
        return super()._get_file_path_stat_encoding('')


def _safe_path(root: Path, relative: str) -> Path:
    parts = relative.split('/')
    if any(
        part in {'.', '..'} or any(char in part for char in '\\:\x00') for part in parts
    ):
        raise web.HTTPNotFound
    try:
        candidate = root.joinpath(*parts).resolve()
    except (OSError, RuntimeError) as error:
        raise web.HTTPNotFound from error
    if not candidate.is_relative_to(root):
        raise web.HTTPNotFound
    return candidate


def _representations(path: Path) -> dict[ContentEncoding, Path]:
    candidates: dict[ContentEncoding, Path] = {ContentEncoding.identity: path}
    for encoding, suffix in _COMPRESSED_SUFFIXES.items():
        candidate = path.with_name(path.name + suffix)
        try:
            info = candidate.lstat()
        except OSError:
            continue
        if S_ISREG(info.st_mode):
            candidates[encoding] = candidate
    return candidates


def _is_asset_path(relative: str) -> bool:
    return relative == 'assets' or relative.startswith('assets/')


def _source_path(root: Path, relative: str) -> Path | None:
    requested = _safe_path(root, relative)
    if _is_asset_path(relative):
        if not requested.is_file():
            raise web.HTTPNotFound
        return requested
    index = _safe_path(root, 'index.html')
    if index.is_file():
        return index
    return None


def _cache_control(relative: str) -> str:
    if _is_asset_path(relative):
        return 'public, max-age=31536000, immutable'
    return 'no-cache'


def _select_asset(root: Path, relative: str, header: str) -> _Asset | None:
    source = _source_path(root, relative)
    if source is None:
        return None
    candidates = _representations(source)
    available = [item for item in _ENCODING_PRIORITY if item in candidates]
    encoding = select_encoding(header, available)
    if encoding is None:
        raise web.HTTPNotAcceptable
    return _Asset(
        candidates[encoding],
        mimetypes.guess_type(source)[0] or 'application/octet-stream',
        encoding,
        _cache_control(relative),
    )


def _asset_response(asset: _Asset) -> web.FileResponse:
    headers = {
        'Content-Type': asset.content_type,
        'Cache-Control': asset.cache_control,
        'Vary': 'Accept-Encoding',
    }
    if asset.encoding != ContentEncoding.identity:
        headers['Content-Encoding'] = asset.encoding.value
    return _SelectedFile(asset.path, headers=headers)


class StaticUI:
    """Serve the application shell or a plain-text library notice as HTML."""

    def __init__(self, directory: Path, notice: LibraryNotice | None) -> None:
        self._directory = directory.resolve()
        self._notice = notice

    async def respond(self, request: web.Request) -> web.StreamResponse:
        if self._notice is not None:
            return _notice_response(self._notice)
        header = ','.join(request.headers.getall('Accept-Encoding', []))
        asset = await asyncio.to_thread(
            _select_asset, self._directory, request.match_info['path'], header
        )
        if asset is None:
            return _notice_response(_MISSING_BUILD, status=503)
        return _asset_response(asset)


def _notice_response(notice: LibraryNotice, *, status: int = 200) -> web.Response:
    return web.Response(
        status=status,
        text=notice_page(notice),
        content_type='text/html',
        headers={'Cache-Control': 'no-cache'},
    )
