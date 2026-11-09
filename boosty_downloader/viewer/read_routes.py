"""Read-only HTTP routes over injected library and body-renderer ports."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiohttp import web

from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.detail import post_detail_response
from boosty_downloader.viewer.mapping import author_response, posts_response
from boosty_downloader.viewer.media import serve_media
from boosty_downloader.viewer.media_mapping import media_page_response
from boosty_downloader.viewer.media_paths import is_author_component
from boosty_downloader.viewer.query import (
    library_media_filters,
    library_media_view,
    library_post_filters,
    parse_media_filters,
    parse_post_filters,
)
from boosty_downloader.viewer.responses import model_response

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import LibraryReader, PostBodyRenderer
    from boosty_downloader.domain.library import PostFilters
    from boosty_downloader.domain.library_media import LibraryMediaView, MediaFilters


def _author_name(request: web.Request) -> str:
    author = request.match_info['author']
    if not is_author_component(author):
        raise web.HTTPNotFound
    return author


@dataclass(frozen=True, slots=True)
class ReadRoutes:
    """Run library I/O, path inspection and body rendering in worker threads."""

    reader: LibraryReader
    root: Path
    renderer: PostBodyRenderer

    def register(self, app: web.Application) -> None:
        app.router.add_get('/api/authors', self.authors)
        app.router.add_get('/api/authors/{author}', self.author)
        app.router.add_get('/api/authors/{author}/posts', self.posts)
        app.router.add_get('/api/authors/{author}/media', self.media_list)
        app.router.add_get('/api/authors/{author}/tags', self.tags)
        app.router.add_get('/api/authors/{author}/posts/{post_id}', self.post)
        app.router.add_get('/media/{author}/{path:.*}', self.media)

    async def authors(self, request: web.Request) -> web.Response:
        del request
        return await asyncio.to_thread(self._authors)

    def _authors(self) -> web.Response:
        return web.json_response(
            [
                author_response(author).model_dump(mode='json')
                for author in self.reader.authors()
            ]
        )

    async def author(self, request: web.Request) -> web.Response:
        return await asyncio.to_thread(self._author, _author_name(request))

    def _author(self, author: str) -> web.Response:
        result = self.reader.author(author)
        if result is None:
            raise web.HTTPNotFound
        return model_response(author_response(result))

    async def posts(self, request: web.Request) -> web.Response:
        filters = library_post_filters(parse_post_filters(request.query))
        return await asyncio.to_thread(self._posts, _author_name(request), filters)

    def _posts(self, author: str, filters: PostFilters) -> web.Response:
        if not self.reader.has_author(author):
            raise web.HTTPNotFound
        result = posts_response(author, self.reader.list_posts(author, filters))
        return model_response(result)

    async def media_list(self, request: web.Request) -> web.Response:
        filters = parse_media_filters(request.query)
        return await asyncio.to_thread(
            self._media_list,
            _author_name(request),
            library_media_view(filters.view),
            library_media_filters(filters),
        )

    def _media_list(
        self, author: str, view: LibraryMediaView, filters: MediaFilters
    ) -> web.Response:
        if not self.reader.has_author(author):
            raise web.HTTPNotFound
        result = media_page_response(
            author, self.reader.list_media(author, view, filters)
        )
        return model_response(result)

    async def tags(self, request: web.Request) -> web.Response:
        return await asyncio.to_thread(self._tags, _author_name(request))

    def _tags(self, author: str) -> web.Response:
        if not self.reader.has_author(author):
            raise web.HTTPNotFound
        return web.json_response(
            [
                api.TagCount(tag=item.tag, count=item.count).model_dump(mode='json')
                for item in self.reader.tags(author)
            ]
        )

    async def post(self, request: web.Request) -> web.Response:
        return await asyncio.to_thread(
            self._post, _author_name(request), request.match_info['post_id']
        )

    def _post(self, author: str, post_id: str) -> web.Response:
        result = self.reader.post(author, post_id)
        if result is None:
            raise web.HTTPNotFound
        body = post_detail_response(author, result, self.root, self.renderer)
        return model_response(body)

    async def media(self, request: web.Request) -> web.StreamResponse:
        return await serve_media(request, reader=self.reader, library_root=self.root)
