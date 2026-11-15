"""Open indexed library files only for a browser on this computer."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

from aiohttp import web
from pydantic import TypeAdapter

from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.file_types import file_type
from boosty_downloader.viewer.guard import (
    is_address_host,
    is_open_allowed,
    is_origin_allowed,
    is_same_machine,
)
from boosty_downloader.viewer.media_identity import decode_media_identity
from boosty_downloader.viewer.media_paths import (
    is_author_component,
    resolve_author_path,
    resolve_post_folder,
)
from boosty_downloader.viewer.opener import OpenError
from boosty_downloader.viewer.requests import read_body, require_empty_request
from boosty_downloader.viewer.responses import error_response, model_response
from boosty_downloader.viewer.urls import author_relative_path

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from boosty_downloader.application.ports import LibraryReader
    from boosty_downloader.domain.library_media import MediaIdentity
    from boosty_downloader.viewer.opener import Opener

_MEDIA_REQUEST = TypeAdapter(api.OpenMediaRequest)
_POST_REQUEST = TypeAdapter(api.OpenPostRequest)
_ERROR_OPEN_NOT_ALLOWED: Final = 'open_not_allowed'
_ERROR_OPEN_FAILED: Final = 'open_failed'


def _capabilities_response(capabilities: api.OpenerCapabilities) -> web.Response:
    response = model_response(capabilities)
    response.headers['Cache-Control'] = 'no-store'
    return response


def _disabled_capabilities() -> web.Response:
    return _capabilities_response(
        api.OpenerCapabilities(open=False, reveal=False, folders=False, sep=os.sep)
    )


async def disabled_opener(request: web.Request) -> web.Response:
    """Grant no local actions or filesystem paths for an unavailable library."""
    await require_empty_request(request)
    return _disabled_capabilities()


def _refused(message: str) -> web.Response:
    return error_response(403, _ERROR_OPEN_NOT_ALLOWED, message)


def _author_name(request: web.Request) -> str:
    author = request.match_info['author']
    if not is_author_component(author):
        raise web.HTTPNotFound
    return author


def _run_opener(action: Callable[[Path], None], path: Path) -> web.Response:
    try:
        action(path)
    except OpenError as error:
        return error_response(409, _ERROR_OPEN_FAILED, str(error))
    return web.Response(status=204)


def _regular_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _media_action(opener: Opener, *, reveal: bool) -> Callable[[Path], None] | None:
    match reveal:
        case True:
            return opener.reveal
        case False:
            return opener.open


@dataclass(frozen=True, slots=True)
class OpenRoutes:
    """Resolve recorded identities and run native actions outside the event loop."""

    reader: LibraryReader
    root: Path
    opener: Opener

    def register(self, app: web.Application) -> None:
        app.router.add_get('/api/opener', self.capabilities)
        app.router.add_post('/api/authors/{author}/media/{media_id}/open', self.media)
        app.router.add_post('/api/authors/{author}/posts/{post_id}/open', self.post)

    async def capabilities(self, request: web.Request) -> web.Response:
        await require_empty_request(request)
        if (
            not is_same_machine(request)
            or not is_address_host(request)
            or not is_origin_allowed(request)
        ):
            return _disabled_capabilities()
        return await asyncio.to_thread(self._capabilities)

    def _capabilities(self) -> web.Response:
        can_open = self.opener.open is not None
        can_reveal = self.opener.reveal is not None
        if not can_open and not can_reveal:
            return _disabled_capabilities()
        return _capabilities_response(
            api.OpenerCapabilities(
                open=can_open,
                reveal=can_reveal,
                folders=can_open and self.opener.folders,
                system=self.opener.system,
                root=str(self.root.resolve()),
                sep=os.sep,
            )
        )

    async def media(self, request: web.Request) -> web.Response:
        if not is_open_allowed(request):
            return _refused('Only the local viewer page may open files.')
        body = await read_body(request, _MEDIA_REQUEST)
        identity = decode_media_identity(request.match_info['media_id'])
        return await asyncio.to_thread(
            self._media, _author_name(request), identity, reveal=body.reveal
        )

    def _media(
        self, author: str, identity: MediaIdentity, *, reveal: bool
    ) -> web.Response:
        action = _media_action(self.opener, reveal=reveal)
        if action is None:
            return _refused('This computer cannot perform the requested file action.')
        stored = self._media_path(author, identity)
        relative = author_relative_path(author, stored)
        if relative is None:
            raise web.HTTPNotFound
        path = resolve_author_path(self.root, author, relative)
        if path is None or not _regular_file(path):
            raise web.HTTPNotFound
        if not reveal and file_type(PurePosixPath(stored).name) != file_type(path.name):
            return _refused(
                'A link to another file type can only be shown in its folder.'
            )
        return _run_opener(action, path)

    def _media_path(self, author: str, identity: MediaIdentity) -> str:
        if not self.reader.has_author(author):
            raise web.HTTPNotFound
        stored = self.reader.media_path(author, identity)
        if stored is None:
            raise web.HTTPNotFound
        return stored

    async def post(self, request: web.Request) -> web.Response:
        if not is_open_allowed(request):
            return _refused('Only the local viewer page may open folders.')
        await read_body(request, _POST_REQUEST)
        return await asyncio.to_thread(
            self._post, _author_name(request), request.match_info['post_id']
        )

    def _post(self, author: str, post_id: str) -> web.Response:
        if self.opener.open is None or not self.opener.folders:
            return _refused('This computer cannot open post folders.')
        if not self.reader.has_author(author):
            raise web.HTTPNotFound
        stored = self.reader.post_folder(author, post_id)
        if stored is None:
            raise web.HTTPNotFound
        folder = resolve_post_folder(self.root, author, stored)
        if folder is None:
            raise web.HTTPNotFound
        return _run_opener(self.opener.open, folder)
