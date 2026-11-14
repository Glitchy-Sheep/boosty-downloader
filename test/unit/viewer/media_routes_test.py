"""Indexed media HTTP views preserve counts, marks and portable item identities."""

from __future__ import annotations

import asyncio
import gzip
import threading
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import update
from support.viewer_read_library import (
    AUDIO_ID,
    AUDIO_PATH,
    IMAGE_PATH,
    NOW,
    OLD_ID,
    POST_ID,
    ReadLibrary,
    make_library,
    make_record,
    save_record,
)

from boosty_downloader.application.post_body_renderer import StoredPostBodyRenderer
from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.stored_post import LockedPost
from boosty_downloader.infrastructure.library._index_engine import make_index_engine
from boosty_downloader.infrastructure.library._index_models import IndexMedia
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.app import create_app
from boosty_downloader.viewer.media_identity import (
    decode_media_identity,
    media_identity,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from aiohttp import web

    from boosty_downloader.domain.library_media import (
        LibraryMediaPage,
        LibraryMediaView,
        MediaFilters,
    )

_REMOVED_VIDEO = 'external_video:https://example.test/watch?a=b:c'
_ALL_IDS = ('image:cover', AUDIO_ID, 'boosty_video:old', _REMOVED_VIDEO)
_COUNTS = api.MediaViewCounts(all=4, images=1, videos=2, audio=1, files=1)
_UNSEEN_COUNTS = api.MediaViewCounts(all=2, videos=1, audio=1)
_FAVORITE_COUNTS = api.MediaViewCounts(all=3, images=1, videos=1, audio=1, files=1)


@dataclass(frozen=True, slots=True)
class _HTTPFixture:
    library: ReadLibrary
    client: TestClient[web.Request, web.Application]


@dataclass(frozen=True, slots=True)
class _FilterCase:
    query: str
    media_ids: tuple[str, ...]
    counts: api.MediaViewCounts = _COUNTS
    missing: int = 1


@pytest.fixture
async def http(tmp_path: Path) -> AsyncIterator[_HTTPFixture]:
    library = make_library(tmp_path / 'library')
    app = create_app(
        reader=library.reader,
        library_root=library.root,
        body_renderer=StoredPostBodyRenderer(),
    )
    async with TestClient(TestServer(app)) as client:
        yield _HTTPFixture(library, client)


async def _media(http: _HTTPFixture, query: str = '') -> api.MediaPage:
    response = await http.client.get(f'/api/authors/writer/media{query}')
    assert response.status == 200, await response.text()
    return api.MediaPage.model_validate(await response.json())


@pytest.mark.parametrize(
    'case',
    [
        _FilterCase('', _ALL_IDS),
        _FilterCase('?view=all', _ALL_IDS),
        _FilterCase('?view=images', ('image:cover',), missing=0),
        _FilterCase('?view=videos', ('boosty_video:old', _REMOVED_VIDEO)),
        _FilterCase('?view=audio', (AUDIO_ID,), missing=0),
        _FilterCase('?view=files', ('file:removed',)),
        _FilterCase(
            '?order=oldest',
            ('boosty_video:old', 'image:cover', AUDIO_ID, _REMOVED_VIDEO),
        ),
        _FilterCase('?unseen=1', (AUDIO_ID, _REMOVED_VIDEO), _UNSEEN_COUNTS),
        _FilterCase(
            '?fav=1', ('image:cover', AUDIO_ID, _REMOVED_VIDEO), _FAVORITE_COUNTS
        ),
        _FilterCase(
            '?view=videos&unseen=1&fav=1&order=oldest',
            (_REMOVED_VIDEO,),
            _UNSEEN_COUNTS,
        ),
        _FilterCase('?view=files&unseen=1', (), _UNSEEN_COUNTS),
        _FilterCase('?view=images&unseen=1', (), _UNSEEN_COUNTS, missing=0),
        _FilterCase('?view=all&unseen=0&fav=0&order=newest', _ALL_IDS),
    ],
)
async def test_views_filters_and_order_keep_shared_counts(
    http: _HTTPFixture, case: _FilterCase
) -> None:
    result = await _media(http, case.query)
    assert tuple(decode_media_identity(item.id).media_id for item in result.items) == (
        case.media_ids
    )
    assert result.counts == case.counts
    assert result.missing == case.missing
    assert set(result.posts) == {item.post_id for item in result.items}


async def test_complete_response_shares_post_data_and_preserves_unicode_paths(
    http: _HTTPFixture,
) -> None:
    response = await http.client.get('/api/authors/writer/media')
    body = await response.json()
    assert set(body) == set(api.MediaPage.model_fields)
    assert all(set(item) == set(api.MediaItem.model_fields) for item in body['items'])
    assert all(
        set(post) == set(api.MediaPost.model_fields) for post in body['posts'].values()
    )
    page = api.MediaPage.model_validate(body)
    assert len(page.items) == 4
    assert set(page.posts) == {POST_ID, OLD_ID}
    folder = http.library.folder.partition('/')[2]
    image, audio, _, removed = page.items
    assert image.path == image.thumb_path == f'{folder}/{IMAGE_PATH}'
    assert image.file_type == 'image'
    assert audio.path == f'{folder}/{AUDIO_PATH}'
    assert audio.filename == 'песня 100% #.mp3'
    assert audio.id == media_identity(POST_ID, AUDIO_ID)
    assert audio.kind == audio.file_type == 'audio'
    assert audio.title == 'A track'
    assert audio.artist == 'An artist'
    assert audio.size == 15
    assert audio.duration_s == 90
    assert audio.position_s == 34
    assert audio.created_at == NOW
    assert audio.thumb_path is None
    assert not audio.finished
    assert [item.removed for item in page.items] == [False, False, False, True]
    assert decode_media_identity(removed.id).media_id == _REMOVED_VIDEO
    assert page.posts[POST_ID] == api.MediaPost(
        title='Shader lesson',
        cover_path=f'{folder}/{IMAGE_PATH}',
        seen=True,
        favorite=True,
    )
    assert (await _media(http, '?unseen=1')).posts[POST_ID].seen


@pytest.mark.parametrize(
    'query',
    [
        '?unknown=1',
        '?q=text',
        '?tag=lesson',
        '?kind=images',
        '?locked=1',
        '?incomplete=1',
        '?view=all&view=all',
        '?order=newest&order=oldest',
        '?unseen=0&unseen=1',
        '?fav=1&fav=1',
        '?view=',
        '?view=image',
        '?view=video',
        '?order=',
        '?order=latest',
        '?unseen=true',
        '?unseen=',
        '?unseen=01',
        '?fav=false',
        '?fav=2',
        '?fav=-1',
    ],
)
async def test_invalid_media_filters_return_structured_400(
    http: _HTTPFixture, query: str
) -> None:
    response = await http.client.get(f'/api/authors/writer/media{query}')
    error = api.ErrorResponse.model_validate(await response.json())
    assert response.status == 400
    assert error.error.code == 'invalid_query'


async def test_known_empty_author_and_unknown_author_stay_distinct(
    http: _HTTPFixture,
) -> None:
    response = await http.client.get('/api/authors/empty/media')
    assert response.status == 200
    assert api.MediaPage.model_validate(await response.json()) == api.MediaPage()
    response = await http.client.get('/api/authors/missing/media')
    assert response.status == 404
    assert (
        api.ErrorResponse.model_validate(await response.json()).error.code
        == 'not_found'
    )


async def test_finished_pieces_leave_unseen_even_when_added_after_seen(
    http: _HTTPFixture,
) -> None:
    JsonPostMarks(http.library.root).save_marks(
        'writer',
        POST_ID,
        PostMarks(
            seen_at=NOW - timedelta(days=1),
            favorite=True,
            positions={AUDIO_ID: PlaybackPosition(0, NOW)},
        ),
    )
    http.library.reader.prepare()
    page = await _media(http, '?unseen=1&fav=1')
    assert [decode_media_identity(item.id).media_id for item in page.items] == [
        _REMOVED_VIDEO
    ]
    assert page.counts == api.MediaViewCounts(all=1, videos=1)
    assert page.posts[POST_ID].seen
    audio = (await _media(http, '?view=audio')).items[0]
    assert audio.finished
    assert audio.position_s == 0


async def test_retained_locked_downloads_stay_listed_and_counted(
    http: _HTTPFixture,
) -> None:
    before = await _media(http, '?unseen=1&fav=1')
    metadata = replace(http.library.record.post, title='Currently locked')
    http.library.store.save_locked_post(LockedPost(metadata, NOW + timedelta(days=1)))
    http.library.reader.prepare()
    after = await _media(http, '?unseen=1&fav=1')
    assert after.items == before.items
    assert after.counts == before.counts
    assert after.missing == before.missing
    assert after.posts[POST_ID] == before.posts[POST_ID].model_copy(
        update={'title': 'Currently locked'}
    )


async def test_same_media_key_in_matching_post_prefixes_has_distinct_identity(
    http: _HTTPFixture,
) -> None:
    record = make_record('bbbbbbbb-second', 'Second track')
    record.media[AUDIO_ID] = replace(http.library.record.media[AUDIO_ID])
    save_record(http.library.root, http.library.store, record)
    http.library.reader.prepare()
    page = await _media(http, '?view=audio')
    assert [item.post_id for item in page.items] == [record.post.id, POST_ID]
    assert len({item.id for item in page.items}) == 2
    assert set(page.posts) == {record.post.id, POST_ID}


def _update_media(library: ReadLibrary, media_id: str, **values: object) -> None:
    engine = make_index_engine(LibraryIndex(library.root).path, writable=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                update(IndexMedia)
                .where(IndexMedia.post_id == POST_ID, IndexMedia.media_id == media_id)
                .values(**values)
            )
    finally:
        engine.dispose()


async def test_explicit_thumbnail_can_live_outside_the_post_folder(
    http: _HTTPFixture,
) -> None:
    path = 'writer/thumbs/кадр 100% #.jpg'
    _update_media(http.library, 'image:cover', thumbnail_path=path)
    page = await _media(http, '?view=images')
    assert page.items[0].thumb_path == 'thumbs/кадр 100% #.jpg'


async def test_video_preview_matches_list_detail_and_playback_responses(
    http: _HTTPFixture,
) -> None:
    entry = http.library.record.media[_REMOVED_VIDEO]
    entry.preview_path = 'previews/кадр 100% #.jpg'
    http.library.store.save_post(http.library.folder, http.library.record)
    http.library.reader.prepare()
    listed = (await _media(http, '?view=videos')).items[-1]
    folder = http.library.folder.partition('/')[2]
    assert listed.thumb_path == f'{folder}/{entry.preview_path}'
    response = await http.client.get(f'/api/authors/writer/posts/{POST_ID}')
    detail = api.PostDetail.model_validate(await response.json())
    assert next(item for item in detail.media if item.id == listed.id) == listed
    response = await http.client.put(
        f'/api/authors/writer/media/{listed.id}/position',
        json={'seconds': 12, 'duration': 100},
    )
    assert response.status == 200
    updated = api.MediaItem.model_validate(await response.json())
    assert updated == listed.model_copy(update={'position_s': 12})
    assert (await _media(http, '?view=videos')).items[-1] == updated


@pytest.mark.parametrize(
    'changes',
    [
        {'size': None},
        {'path': None},
        {'path': 'writer/another-post/file.mp3'},
        {'thumbnail_path': 'another-author/thumbnail.jpg'},
        {'width': -1},
        {'height': -1},
        {'duration': -1},
        {'playback_position': -1},
        {'duration': float('inf')},
        {'duration': 1e100},
        {'playback_position': float('inf')},
        {'size': 1.5},
        {'width': 1.5},
        {'height': 1.5},
    ],
)
async def test_corrupt_index_returns_a_private_structured_409(
    http: _HTTPFixture, changes: dict[str, object]
) -> None:
    _update_media(http.library, AUDIO_ID, **changes)
    response = await http.client.get('/api/authors/writer/media')
    body = await response.text()
    error = api.ErrorResponse.model_validate_json(body)
    assert response.status == 409
    assert error.error.code == 'library_unavailable'
    assert str(http.library.root) not in body
    assert AUDIO_PATH not in body


async def test_zero_byte_download_is_listed_with_its_recorded_size(
    http: _HTTPFixture,
) -> None:
    http.library.record.media['file:removed'].size = 0
    http.library.store.save_post(http.library.folder, http.library.record)
    http.library.reader.prepare()
    page = await _media(http, '?view=files')
    assert len(page.items) == page.counts.files == 1
    assert page.items[0].size == 0
    assert page.items[0].removed


async def test_media_response_compresses_the_complete_page(http: _HTTPFixture) -> None:
    response = await http.client.get(
        '/api/authors/writer/media',
        headers={'Accept-Encoding': 'gzip'},
        auto_decompress=False,
    )
    assert response.status == 200
    assert response.headers['Content-Encoding'] == 'gzip'
    assert 'Accept-Encoding' in response.headers['Vary']
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    body = gzip.decompress(await response.read())
    assert api.MediaPage.model_validate_json(body) == await _media(http)


async def test_slow_media_read_does_not_block_another_request(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = http.library.reader.list_media

    def slow_read(
        author: str, view: LibraryMediaView, filters: MediaFilters
    ) -> LibraryMediaPage:
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=10)
        return original(author, view, filters)

    monkeypatch.setattr(http.library.reader, 'list_media', slow_read)
    slow = asyncio.ensure_future(http.client.get('/api/authors/writer/media'))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        fast = await asyncio.wait_for(http.client.get('/api/authors'), timeout=1)
        assert fast.status == 200
        assert not slow.done()
        await fast.read()
    finally:
        release.set()
        response = await slow
        await response.read()
    assert response.status == 200


async def test_saved_thumbnail_projection_preserves_original_and_cover(
    http: _HTTPFixture,
) -> None:
    entry = http.library.record.media['image:cover']
    entry.thumbnail_path = '.boosty-downloader/thumbs/cover.png'
    http.library.store.save_post(http.library.folder, http.library.record)
    http.library.reader.prepare()
    page = await _media(http, '?view=images')
    image = page.items[0]
    relative_folder = http.library.folder.partition('/')[2]
    assert image.thumb_path == entry.thumbnail_path
    assert image.path == f'{relative_folder}/{IMAGE_PATH}'
    assert image.size == entry.size
    assert page.posts[POST_ID].cover_path == image.path
    assert not (http.library.root / 'writer' / entry.thumbnail_path).exists()
