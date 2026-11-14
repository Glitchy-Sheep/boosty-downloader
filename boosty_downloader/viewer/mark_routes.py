"""User mark and playback mutations through the injected library reader."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from aiohttp import web
from pydantic import TypeAdapter

from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.mapping import author_response, post_response
from boosty_downloader.viewer.mark_progress import BulkMarksCoordinator
from boosty_downloader.viewer.media_identity import decode_media_identity
from boosty_downloader.viewer.media_mapping import media_item_response
from boosty_downloader.viewer.media_paths import is_author_component
from boosty_downloader.viewer.query import library_post_filters
from boosty_downloader.viewer.requests import read_body, require_empty_request
from boosty_downloader.viewer.responses import model_response

if TYPE_CHECKING:
    from boosty_downloader.application.ports import LibraryReader
    from boosty_downloader.domain.library_mutations import MediaIdentity
    from boosty_downloader.viewer.mark_progress import ProgressCallback

_MARK_REQUEST = TypeAdapter(api.MarkRequest)
_BULK_REQUEST = TypeAdapter(api.BulkMarksRequest)
_POSITION_REQUEST = TypeAdapter(api.PositionRequest)


def _author_name(request: web.Request) -> str:
    author = request.match_info['author']
    if not is_author_component(author):
        raise web.HTTPNotFound
    return author


@dataclass(slots=True)
class MarkRoutes:
    """Map mutation results without rendering a post body or reading it again."""

    reader: LibraryReader
    coordinator: BulkMarksCoordinator = field(default_factory=BulkMarksCoordinator)

    def register(self, app: web.Application) -> None:
        app.router.add_put('/api/authors/{author}/posts/{post_id}/marks', self.mark)
        app.router.add_post('/api/authors/{author}/marks', self.bulk)
        app.router.add_get('/api/authors/{author}/marks/progress', self.progress)
        app.router.add_put(
            '/api/authors/{author}/media/{media_id}/position', self.position
        )
        app.on_cleanup.append(self.close)

    async def close(self, app: web.Application) -> None:
        del app
        await self.coordinator.close()

    async def mark(self, request: web.Request) -> web.Response:
        body = await read_body(request, _MARK_REQUEST)
        return await asyncio.to_thread(
            self._mark, _author_name(request), request.match_info['post_id'], body
        )

    def _mark(self, author: str, post_id: str, body: api.MarkRequest) -> web.Response:
        match body:
            case api.SeenMarkRequest(seen=seen):
                result = self.reader.set_seen(author, post_id, seen=seen)
            case api.FavoriteMarkRequest(favorite=favorite):
                result = self.reader.set_favorite(author, post_id, favorite=favorite)
        if result is None:
            raise web.HTTPNotFound
        return model_response(
            api.MarkResult(
                post=post_response(author, result.post),
                author=author_response(result.author),
            )
        )

    async def bulk(self, request: web.Request) -> web.Response:
        body = await read_body(request, _BULK_REQUEST)
        author = _author_name(request)
        if not await asyncio.to_thread(self.reader.has_author, author):
            raise web.HTTPNotFound
        count = await self.coordinator.run(author, partial(self._bulk, author, body))
        if count is None:
            raise web.HTTPNotFound
        return model_response(api.BulkMarksResult(count=count))

    def _bulk(
        self, author: str, body: api.BulkMarksRequest, progress: ProgressCallback
    ) -> int | None:
        return self.reader.set_seen_many(
            author,
            library_post_filters(body.filters),
            seen=body.seen,
            progress=progress,
        )

    async def progress(self, request: web.Request) -> web.Response:
        await require_empty_request(request)
        author = _author_name(request)
        if not await asyncio.to_thread(self.reader.has_author, author):
            raise web.HTTPNotFound
        response = model_response(self.coordinator.progress(author))
        response.headers['Cache-Control'] = 'no-store'
        return response

    async def position(self, request: web.Request) -> web.Response:
        body = await read_body(request, _POSITION_REQUEST)
        identity = decode_media_identity(request.match_info['media_id'])
        return await asyncio.to_thread(
            self._position, _author_name(request), identity, body
        )

    def _position(
        self, author: str, identity: MediaIdentity, body: api.PositionRequest
    ) -> web.Response:
        item = self.reader.set_position(author, identity, body.seconds, body.duration)
        if item is None:
            raise web.HTTPNotFound
        return model_response(media_item_response(author, item))
