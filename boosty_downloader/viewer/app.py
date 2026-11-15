"""Compose the local viewer from a prepared library reader and packaged UI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web

from boosty_downloader.viewer.api_models import (
    ERROR_NOT_FOUND,
    ErrorBody,
    ErrorResponse,
)
from boosty_downloader.viewer.compression import compress_json_responses
from boosty_downloader.viewer.guard import guard_requests, secure_response
from boosty_downloader.viewer.mark_routes import MarkRoutes
from boosty_downloader.viewer.open_routes import OpenRoutes, disabled_opener
from boosty_downloader.viewer.opener import NO_OPENER, Opener
from boosty_downloader.viewer.pages import LibraryNotice
from boosty_downloader.viewer.read_routes import ReadRoutes
from boosty_downloader.viewer.responses import handle_library_errors
from boosty_downloader.viewer.saved_page_media import SavedMediaAccess
from boosty_downloader.viewer.static import StaticUI

if TYPE_CHECKING:
    from boosty_downloader.application.ports import LibraryReader, PostBodyRenderer

LIBRARY_READER: web.AppKey[LibraryReader | None] = web.AppKey('library_reader')

__all__ = ['LIBRARY_READER', 'LibraryNotice', 'create_app']


async def _not_found(request: web.Request) -> web.Response:
    del request
    body = ErrorResponse(error=ErrorBody(code=ERROR_NOT_FOUND, message='Not found.'))
    return web.json_response(body.model_dump(mode='json'), status=404)


def create_app(  # noqa: PLR0913 - explicit injected services and UI options
    *,
    reader: LibraryReader | None,
    library_root: Path | None = None,
    body_renderer: PostBodyRenderer | None = None,
    notice: LibraryNotice | None = None,
    static_directory: Path | None = None,
    opener: Opener = NO_OPENER,
) -> web.Application:
    """Build routes without opening storage, networking or library files."""
    app = web.Application(
        middlewares=[compress_json_responses, guard_requests, handle_library_errors]
    )
    app[LIBRARY_READER] = reader
    app.on_response_prepare.append(secure_response)
    if reader is not None:
        if library_root is None or body_renderer is None:
            message = 'A library reader requires its root and body renderer.'
            raise ValueError(message)
        ReadRoutes(reader, library_root, body_renderer, SavedMediaAccess()).register(
            app
        )
        MarkRoutes(reader).register(app)
        OpenRoutes(reader, library_root, opener).register(app)
    else:
        app.router.add_get('/api/opener', disabled_opener)
    for prefix in ('api', 'media', 'thumbs'):
        app.router.add_route('*', f'/{prefix}', _not_found)
        app.router.add_route('*', f'/{prefix}/{{path:.*}}', _not_found)
    directory = static_directory or Path(__file__).parent / 'static' / 'app'
    app.router.add_get('/{path:.*}', StaticUI(directory, notice).respond)
    return app
