"""Live capture keeps blog metadata separate from post observations."""

from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from api_schema import __main__ as capture
from api_schema import live_api
from api_schema.observed_shapes import ObservedObject, observe
from api_schema.openapi_document import build_openapi_document
from api_schema.unread_keys import keys_unread_by_client
from support.synthetic_blog import synthetic_blog


@pytest.mark.parametrize('has_posts', [False, True])
async def test_capture_reads_metadata_in_every_view(
    monkeypatch: pytest.MonkeyPatch, *, has_posts: bool
) -> None:
    metadata = AsyncMock(return_value=synthetic_blog())
    post = {'id': 'fixture-post', 'data': []}
    listing = AsyncMock(
        return_value=[
            {
                'data': [post] if has_posts else [],
                'extra': {'isLast': True, 'offset': ''},
            }
        ]
    )
    single = AsyncMock(return_value=post)
    monkeypatch.setattr(capture, 'fetch_blog_info', metadata)
    monkeypatch.setattr(capture, 'fetch_listing_pages', listing)
    monkeypatch.setattr(capture, 'fetch_single_post', single)

    result = await capture._observe_blog_answers(
        ['example', 'other_author'], ['fake-token', None], 1
    )

    assert metadata.await_count == 4
    assert listing.await_count == 4
    assert single.await_count == (4 if has_posts else 0)
    assert [call.args[1] for call in metadata.await_args_list] == [
        'example',
        'other_author',
        'example',
        'other_author',
    ]
    assert result.blog.samples == 4
    assert result.page.samples == 4
    assert result.post.samples == (8 if has_posts else 0)
    assert 'description' not in result.post.keys
    observed = build_openapi_document(result)['x-observed']
    assert observed['blog_info']['samples'] == {'blogs': 2, 'views': 2, 'responses': 4}


async def test_blog_fetcher_requests_the_metadata_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def metadata(request: web.Request) -> web.Response:
        assert request.path == '/v1/blog/example'
        assert not request.query
        return web.json_response(synthetic_blog())

    app = web.Application()
    app.router.add_get('/v1/blog/example', metadata)
    async with TestServer(app) as server, live_api.open_api_session(None) as session:
        monkeypatch.setattr(
            live_api, 'BOOSTY_DEFAULT_BASE_URL', str(server.make_url('/v1/'))
        )
        assert await live_api.fetch_blog_info(session, 'example') == synthetic_blog()


def test_unread_blog_fields_and_description_chunks_use_their_own_components() -> None:
    blog = ObservedObject()
    observe(
        blog,
        {
            **synthetic_blog(),
            'futureField': True,
            'description': [
                {'type': 'text', 'content': '', 'modificator': '', 'blogOnly': True}
            ],
        },
    )
    post = ObservedObject()
    observe(
        post,
        {
            'data': [
                {'type': 'text', 'content': '', 'modificator': '', 'postOnly': True}
            ]
        },
    )

    assert keys_unread_by_client(post, ObservedObject(), blog) == {
        'BlogInfo': ['futureField'],
        'ChunkText': ['postOnly'],
        'BlogDescriptionChunkText': ['blogOnly'],
    }
