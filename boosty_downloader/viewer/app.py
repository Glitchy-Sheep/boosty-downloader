"""Compose the local viewer from a prepared library reader and packaged UI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from boosty_downloader.viewer.compression import compress_json_responses
from boosty_downloader.viewer.guard import guard_requests, secure_response
from boosty_downloader.viewer.pages import LibraryNotice
from boosty_downloader.viewer.static import StaticUI

if TYPE_CHECKING:
    from boosty_downloader.application.ports import LibraryReader

LIBRARY_READER: web.AppKey[LibraryReader | None] = web.AppKey('library_reader')

__all__ = ['LIBRARY_READER', 'LibraryNotice', 'create_app']


async def _not_found(request: web.Request) -> web.Response:
    del request
    return web.json_response({'error': 'Not found.'}, status=404)


def create_app(
    *,
    reader: LibraryReader | None,
    notice: LibraryNotice | None = None,
    static_directory: Path | None = None,
) -> web.Application:
    """Build routes without opening storage, networking or library files."""
    app = web.Application(middlewares=[compress_json_responses, guard_requests])
    app[LIBRARY_READER] = reader
    app.on_response_prepare.append(secure_response)
    for prefix in ('api', 'media'):
        app.router.add_route('*', f'/{prefix}', _not_found)
        app.router.add_route('*', f'/{prefix}/{{path:.*}}', _not_found)
    directory = static_directory or Path(__file__).parent / 'static' / 'app'
    app.router.add_get('/{path:.*}', StaticUI(directory, notice).respond)
    return app
