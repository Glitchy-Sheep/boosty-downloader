"""HTTP marks persist through the library ports and preserve guarded write semantics."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from aiohttp.test_utils import TestClient, TestServer
from support.viewer_read_library import (
    AUDIO_ID,
    LOCKED_ID,
    NOW,
    POST_ID,
    ReadLibrary,
    make_library,
)

from boosty_downloader.application.post_body_renderer import StoredPostBodyRenderer
from boosty_downloader.domain.library_errors import LibraryWriteError
from boosty_downloader.domain.stored_post import LockedPost
from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.app import create_app
from boosty_downloader.viewer.media_identity import media_identity

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable
    from pathlib import Path

    from aiohttp import ClientResponse, web

    from boosty_downloader.domain.library import PostFilters
    from boosty_downloader.domain.library_mutations import BulkMarkProgress

_POST_MARK = f'/api/authors/writer/posts/{POST_ID}/marks'
_BULK_MARK = '/api/authors/writer/marks'
_PROGRESS = f'{_BULK_MARK}/progress'
_POSITION = f'/api/authors/writer/media/{media_identity(POST_ID, AUDIO_ID)}/position'


@dataclass(frozen=True, slots=True)
class _HTTPFixture:
    library: ReadLibrary
    client: TestClient[web.Request, web.Application]


@pytest.fixture
async def http(tmp_path: Path) -> AsyncIterator[_HTTPFixture]:
    library = make_library(tmp_path / 'library')
    app = create_app(
        reader=library.reader,
        library_root=library.root,
        body_renderer=StoredPostBodyRenderer(),
    )
    async with TestClient(TestServer(app, handler_cancellation=True)) as client:
        yield _HTTPFixture(library, client)


async def _error(response: ClientResponse, status: int, code: str) -> None:
    assert response.status == status, await response.text()
    body = api.ErrorResponse.model_validate(await response.json())
    assert body.error.code == code
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert 'frame-ancestors' in response.headers['Content-Security-Policy']


async def _detail(http: _HTTPFixture) -> api.PostDetail:
    response = await http.client.get(f'/api/authors/writer/posts/{POST_ID}')
    assert response.status == 200
    return api.PostDetail.model_validate(await response.json())


async def test_single_marks_update_fresh_post_author_and_keep_other_fields(
    http: _HTTPFixture,
) -> None:
    before = await _detail(http)
    assert before.updated
    assert before.favorite
    response = await http.client.put(_POST_MARK, json={'seen': True})
    assert response.status == 200
    marked = api.MarkResult.model_validate(await response.json())
    assert marked.post.seen
    assert not marked.post.updated
    assert marked.post.favorite
    assert marked.author.unseen == 1
    assert (await _detail(http)).media == before.media
    response = await http.client.put(_POST_MARK, json={'favorite': False})
    favorite = api.MarkResult.model_validate(await response.json())
    assert favorite.post.seen
    assert not favorite.post.favorite
    assert favorite.author.favorites == 0
    response = await http.client.put(_POST_MARK, json={'seen': False})
    unseen = api.MarkResult.model_validate(await response.json())
    assert not unseen.post.seen
    assert unseen.author.unseen == 2
    marks = http.library.reader.get_marks('writer', POST_ID)
    assert marks is not None
    assert marks.seen_at is None
    assert not marks.favorite
    assert marks.positions[AUDIO_ID].seconds == 34


async def test_bulk_uses_complete_filtered_snapshot_counts_changes_and_skips_locked(
    http: _HTTPFixture,
) -> None:
    response = await http.client.post(
        _BULK_MARK, json={'seen': True, 'filters': {'unseen': True}}
    )
    assert response.status == 200
    assert await response.json() == {'count': 2}
    response = await http.client.get('/api/authors/writer/posts?unseen=1')
    assert (await response.json())['total'] == 0
    response = await http.client.post(_BULK_MARK, json={'seen': True, 'filters': {}})
    assert await response.json() == {'count': 0}
    response = await http.client.post(
        _BULK_MARK, json={'seen': False, 'filters': {'tag': 'text'}}
    )
    assert await response.json() == {'count': 1}
    response = await http.client.post(
        _BULK_MARK, json={'seen': True, 'filters': {'locked': True}}
    )
    assert await response.json() == {'count': 0}
    response = await http.client.get(_PROGRESS)
    assert response.headers['Cache-Control'] == 'no-store'
    assert api.BulkMarksProgressResponse.model_validate(
        await response.json()
    ) == api.BulkMarksProgressResponse(active=False)


@pytest.mark.parametrize(
    ('seconds', 'duration', 'finished', 'position'),
    [
        (12.5, 90, False, 12.5),
        (22.79, 24, False, 22.79),
        (22.8, 24, True, 0),
        (3590, 3600, True, 0),
        (3601, 3600, True, 0),
        (120, 0, False, 120),
    ],
)
async def test_position_response_matches_detail_and_completion_boundary(
    http: _HTTPFixture,
    seconds: float,
    duration: float,
    *,
    finished: bool,
    position: float,
) -> None:
    response = await http.client.put(
        _POSITION, json={'seconds': seconds, 'duration': duration}
    )
    assert response.status == 200, await response.text()
    item = api.MediaItem.model_validate(await response.json())
    assert item.finished is finished
    assert item.position_s == position
    detail = await _detail(http)
    assert next(media for media in detail.media if media.id == item.id) == item
    assert item.duration_s == 90
    assert detail.favorite
    assert detail.seen


async def test_removed_local_video_and_locked_retained_audio_keep_playback(
    http: _HTTPFixture,
) -> None:
    key = 'external_video:https://example.test/watch?a=b:c'
    route = f'/api/authors/writer/media/{media_identity(POST_ID, key)}/position'
    response = await http.client.put(route, json={'seconds': 5, 'duration': 100})
    assert response.status == 200
    removed = api.MediaItem.model_validate(await response.json())
    assert removed.removed
    assert removed.position_s == 5
    http.library.store.save_locked_post(LockedPost(http.library.record.post, NOW))
    response = await http.client.put(_POSITION, json={'seconds': 8, 'duration': 90})
    assert response.status == 200
    assert (await response.json())['position_s'] == 8
    await _error(
        await http.client.put(_POST_MARK, json={'favorite': False}),
        409,
        'mark_conflict',
    )
    await _error(
        await http.client.put(_POST_MARK, json={'seen': True}), 409, 'mark_conflict'
    )
    assert (await _detail(http)).favorite


@pytest.mark.parametrize(
    'route',
    [
        f'/api/authors/missing/posts/{POST_ID}/marks',
        '/api/authors/writer/posts/unknown/marks',
    ],
)
async def test_unknown_post_marks_return_404(http: _HTTPFixture, route: str) -> None:
    await _error(await http.client.put(route, json={'seen': True}), 404, 'not_found')


async def test_locked_only_and_unknown_bulk_or_media_have_distinct_errors(
    http: _HTTPFixture,
) -> None:
    await _error(
        await http.client.put(
            f'/api/authors/writer/posts/{LOCKED_ID}/marks', json={'seen': True}
        ),
        409,
        'mark_conflict',
    )
    await _error(
        await http.client.post(
            '/api/authors/missing/marks', json={'seen': True, 'filters': {}}
        ),
        404,
        'not_found',
    )
    await _error(
        await http.client.get('/api/authors/missing/marks/progress'), 404, 'not_found'
    )
    await _error(
        await http.client.put(
            '/api/authors/writer/media/invalid/position',
            json={'seconds': 1, 'duration': 90},
        ),
        400,
        'invalid_request',
    )
    unknown = media_identity(POST_ID, 'audio:unknown')
    await _error(
        await http.client.put(
            f'/api/authors/writer/media/{unknown}/position',
            json={'seconds': 1, 'duration': 90},
        ),
        404,
        'not_found',
    )
    image = media_identity(POST_ID, 'image:cover')
    await _error(
        await http.client.put(
            f'/api/authors/writer/media/{image}/position',
            json={'seconds': 1, 'duration': 90},
        ),
        409,
        'mark_conflict',
    )


@pytest.mark.parametrize(
    'body',
    [
        b'\xff',
        b'{',
        b'null',
        b'[]',
        b'{}',
        b'{"seen":1}',
        b'{"seen":"true"}',
        b'{"seen":null}',
        b'{"seen":true,"favorite":true}',
        b'{"seen":true,"extra":1}',
    ],
)
async def test_bad_mark_bodies_are_private_400_without_writes(
    http: _HTTPFixture, body: bytes
) -> None:
    before = http.library.reader.get_marks('writer', POST_ID)
    await _error(
        await http.client.put(
            _POST_MARK, data=body, headers={'Content-Type': 'application/json'}
        ),
        400,
        'invalid_request',
    )
    assert http.library.reader.get_marks('writer', POST_ID) == before


@pytest.mark.parametrize(
    'value', ['true', 'false', '-1', 'NaN', 'Infinity', '-Infinity', '"1"', 'null']
)
@pytest.mark.parametrize('field_name', ['seconds', 'duration'])
async def test_position_rejects_bad_numeric_values(
    http: _HTTPFixture, value: str, field_name: str
) -> None:
    fields = {'seconds': '1', 'duration': '90'}
    fields[field_name] = value
    body = '{"seconds":' + fields['seconds'] + ',"duration":' + fields['duration'] + '}'
    await _error(
        await http.client.put(
            _POSITION, data=body.encode(), headers={'Content-Type': 'application/json'}
        ),
        400,
        'invalid_request',
    )


@pytest.mark.parametrize(
    'filters',
    [
        {'tag': ''},
        {'kind': 'video'},
        {'unseen': 1},
        {'q': None},
        {'order': 'bad'},
        {'unknown': True},
    ],
)
async def test_bulk_rejects_filters_that_get_would_not_accept(
    http: _HTTPFixture, filters: dict[str, object]
) -> None:
    await _error(
        await http.client.post(_BULK_MARK, json={'seen': True, 'filters': filters}),
        400,
        'invalid_request',
    )


async def test_write_routes_and_progress_reject_unused_query_or_body(
    http: _HTTPFixture,
) -> None:
    await _error(
        await http.client.put(f'{_POST_MARK}?seen=0', json={'seen': True}),
        400,
        'invalid_request',
    )
    await _error(
        await http.client.post(
            f'{_BULK_MARK}?tag=x', json={'seen': True, 'filters': {}}
        ),
        400,
        'invalid_request',
    )
    await _error(
        await http.client.put(
            f'{_POSITION}?seconds=2', json={'seconds': 1, 'duration': 90}
        ),
        400,
        'invalid_request',
    )
    await _error(await http.client.get(f'{_PROGRESS}?extra=1'), 400, 'invalid_request')
    await _error(await http.client.get(_PROGRESS, data='{}'), 400, 'invalid_request')


@pytest.mark.parametrize(
    'headers',
    [
        {'Content-Type': 'text/plain'},
        {'Content-Type': 'application/json', 'Origin': 'null'},
        {'Content-Type': 'application/json', 'Origin': 'https://foreign.test'},
        {'Content-Type': 'application/json', 'Sec-Fetch-Site': 'cross-site'},
    ],
)
async def test_existing_write_guards_still_refuse_before_mutation(
    http: _HTTPFixture, headers: dict[str, str]
) -> None:
    before = http.library.reader.get_marks('writer', POST_ID)
    await _error(
        await http.client.put(_POST_MARK, data=b'{"seen":true}', headers=headers),
        403,
        'write_not_allowed',
    )
    assert http.library.reader.get_marks('writer', POST_ID) == before


async def test_same_origin_write_passes_and_foreign_host_retains_421(
    http: _HTTPFixture,
) -> None:
    origin = str(http.client.make_url('/')).rstrip('/')
    response = await http.client.put(
        _POST_MARK,
        json={'seen': True},
        headers={'Origin': origin, 'Sec-Fetch-Site': 'same-origin'},
    )
    assert response.status == 200
    await _error(
        await http.client.put(
            _POST_MARK, json={'seen': False}, headers={'Host': 'foreign.test'}
        ),
        421,
        'host_not_allowed',
    )


async def test_expected_storage_failure_is_409_without_private_path(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*_args: object, **_kwargs: object) -> None:
        message = f'{http.library.root}/private/viewer.json failed'
        raise LibraryWriteError(message)

    monkeypatch.setattr(http.library.reader, 'set_seen', fail)
    response = await http.client.put(_POST_MARK, json={'seen': True})
    await _error(response, 409, 'library_unavailable')
    assert str(http.library.root) not in await response.text()


async def test_parallel_fields_survive_concurrent_http_writes(
    http: _HTTPFixture,
) -> None:
    responses = await asyncio.gather(
        http.client.put(_POST_MARK, json={'seen': False}),
        http.client.put(_POST_MARK, json={'favorite': False}),
        http.client.put(_POSITION, json={'seconds': 19, 'duration': 90}),
    )
    assert [response.status for response in responses] == [200, 200, 200]
    detail = await _detail(http)
    assert not detail.seen
    assert not detail.favorite
    assert (
        next(
            item
            for item in detail.media
            if item.id == media_identity(POST_ID, AUDIO_ID)
        ).position_s
        == 19
    )


async def test_progress_is_visible_during_real_writes_and_disconnect_keeps_busy(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    original = http.library.reader.set_seen_many

    def held(
        author: str,
        filters: PostFilters,
        *,
        seen: bool,
        progress: Callable[[BulkMarkProgress], None] | None = None,
    ) -> int | None:
        def report(value: BulkMarkProgress) -> None:
            if progress is not None:
                progress(value)
            if value.completed == 1:
                entered.set()
                assert release.wait(5)

        return original(author, filters, seen=seen, progress=report)

    monkeypatch.setattr(http.library.reader, 'set_seen_many', held)
    caller = asyncio.create_task(
        http.client.post(_BULK_MARK, json={'seen': True, 'filters': {'unseen': True}})
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        response = await asyncio.wait_for(http.client.get(_PROGRESS), 1)
        state = api.BulkMarksProgressResponse.model_validate(await response.json())
        assert state.active
        assert state.total == 2
        assert state.completed == state.changed == 1
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        await _error(
            await http.client.post(_BULK_MARK, json={'seen': False, 'filters': {}}),
            409,
            'marks_busy',
        )
        assert (await http.client.get('/api/authors/empty/posts')).status == 200
        release.set()
        for _ in range(100):
            response = await http.client.get(_PROGRESS)
            if not (await response.json())['active']:
                break
            await asyncio.sleep(0.01)
        else:
            pytest.fail('Bulk worker did not finish')
        response = await http.client.get('/api/authors/writer/posts?unseen=1')
        assert (await response.json())['total'] == 0
    finally:
        release.set()
