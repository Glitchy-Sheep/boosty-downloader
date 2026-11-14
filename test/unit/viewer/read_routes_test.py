"""The HTTP reader serves coherent canonical snapshots without writes or blocking."""

from __future__ import annotations

import asyncio
import os
import threading
from dataclasses import dataclass, replace
from datetime import timedelta
from hashlib import sha256
from shutil import rmtree
from typing import TYPE_CHECKING, TypeAlias
from urllib.parse import quote

import pytest
from aiohttp.test_utils import TestClient, TestServer
from pydantic import TypeAdapter
from support.viewer_read_library import (
    AUDIO_ID,
    AUDIO_PATH,
    IMAGE_PATH,
    LOCKED_ID,
    MEDIA_BYTES,
    NOW,
    OLD_ID,
    POST_ID,
    TEXT_ID,
    ReadLibrary,
    make_library,
    make_record,
    save_record,
)

from boosty_downloader.application.post_body_renderer import StoredPostBodyRenderer
from boosty_downloader.domain.library import PostIdentity
from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import LockedPost, TextBlock
from boosty_downloader.infrastructure.library.json_store import write_post_record
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.app import create_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from aiohttp import web

    from boosty_downloader.domain.library import LibraryPostDetails

PostIds: TypeAlias = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _HTTPFixture:
    library: ReadLibrary
    client: TestClient[web.Request, web.Application]


@dataclass(frozen=True, slots=True)
class _FilterCase:
    query: str
    ids: PostIds


@dataclass(frozen=True, slots=True)
class _Fingerprint:
    modified_ns: int
    digest: str


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


async def _posts(http: _HTTPFixture, query: str = '') -> api.PostList:
    response = await http.client.get(f'/api/authors/writer/posts{query}')
    assert response.status == 200, await response.text()
    return api.PostList.model_validate(await response.json())


async def _detail(http: _HTTPFixture, post_id: str = POST_ID) -> api.PostDetail:
    response = await http.client.get(f'/api/authors/writer/posts/{post_id}')
    assert response.status == 200, await response.text()
    return api.PostDetail.model_validate(await response.json())


async def test_author_list_and_detail_share_indexed_totals(http: _HTTPFixture) -> None:
    response = await http.client.get('/api/authors')
    assert response.status == 200
    authors = TypeAdapter(list[api.Author]).validate_python(await response.json())
    author = next(item for item in authors if item.name == 'writer')
    response = await http.client.get('/api/authors/writer')
    assert api.Author.model_validate(await response.json()) == author
    assert (author.posts, author.locked, author.unseen, author.favorites) == (
        4,
        1,
        2,
        1,
    )
    assert author.storage == api.MediaStorage(images=10, videos=8, audio=15, files=7)
    assert author.avatar_url == '/media/writer/avatar.jpg'
    assert author.description == 'Two paragraphs\n\nSecond'


async def test_known_empty_author_has_usable_zero_responses(http: _HTTPFixture) -> None:
    response = await http.client.get('/api/authors/empty')
    author = api.Author.model_validate(await response.json())
    assert author.name == 'empty'
    assert author.title == author.description == ''
    assert author.posts == 0
    assert author.avatar_url is None
    response = await http.client.get('/api/authors/empty/posts')
    assert response.status == 200
    assert api.PostList.model_validate(await response.json()) == api.PostList()
    response = await http.client.get('/api/authors/empty/tags')
    assert response.status == 200
    assert TypeAdapter(list[api.TagCount]).validate_python(await response.json()) == []


async def test_author_without_blog_metadata_keeps_a_usable_name(
    http: _HTTPFixture,
) -> None:
    record = make_record('ffffffff-anonymous', 'No blog metadata')
    record.post.author = 'unknown_details'
    save_record(http.library.root, http.library.store, record)
    http.library.reader.prepare()
    response = await http.client.get('/api/authors/unknown_details')
    author = api.Author.model_validate(await response.json())
    assert author.name == 'unknown_details'
    assert author.title == author.description == ''
    assert author.avatar_url is None
    assert author.posts == author.unseen == 1


@pytest.mark.parametrize(
    'path',
    [
        '/api/authors/missing',
        '/api/authors/missing/posts',
        '/api/authors/missing/tags',
        '/api/authors/missing/posts/anything',
        '/api/authors/writer/posts/missing',
    ],
)
async def test_unknown_resources_have_structured_404(
    http: _HTTPFixture, path: str
) -> None:
    response = await http.client.get(path)
    error = api.ErrorResponse.model_validate(await response.json())
    assert response.status == 404
    assert error.error.code == 'not_found'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'


@pytest.mark.parametrize(
    'case',
    [
        _FilterCase('', (LOCKED_ID, POST_ID, TEXT_ID, OLD_ID)),
        _FilterCase('?order=oldest', (OLD_ID, TEXT_ID, POST_ID, LOCKED_ID)),
        _FilterCase('?kind=images', (LOCKED_ID, POST_ID)),
        _FilterCase('?kind=videos', (LOCKED_ID, POST_ID, OLD_ID)),
        _FilterCase('?kind=audio', (LOCKED_ID, POST_ID)),
        _FilterCase('?kind=files', (LOCKED_ID, POST_ID)),
        _FilterCase('?unseen=1', (POST_ID, TEXT_ID)),
        _FilterCase('?fav=1', (POST_ID,)),
        _FilterCase('?tag=lesson', (POST_ID,)),
        _FilterCase('?tag=Lesson', ()),
        _FilterCase('?locked=1', (LOCKED_ID,)),
        _FilterCase('?incomplete=1', (POST_ID,)),
        _FilterCase('?q=все', (TEXT_ID,)),
        _FilterCase('?q=шейд', (TEXT_ID,)),
        _FilterCase(
            '?q=shad&kind=audio&unseen=1&fav=1&tag=lesson&incomplete=1&order=oldest',
            (POST_ID,),
        ),
        _FilterCase(
            '?q=shad&kind=audio&unseen=1&fav=1&tag=lesson&incomplete=1&locked=1', ()
        ),
        _FilterCase(
            '?q=&unseen=0&fav=0&locked=0&incomplete=0',
            (LOCKED_ID, POST_ID, TEXT_ID, OLD_ID),
        ),
    ],
)
async def test_filters_select_one_consistent_list(
    http: _HTTPFixture, case: _FilterCase
) -> None:
    result = await _posts(http, case.query)
    assert tuple(row.id for row in result.rows) == case.ids
    assert result.total == len(case.ids) == sum(month.count for month in result.months)
    assert sum(
        month.count for month in result.months if month.month == '2026-10'
    ) == int(OLD_ID in case.ids)


@pytest.mark.parametrize(
    'query',
    [
        '?unknown=1',
        '?q=a&q=b',
        '?fav=1&fav=1',
        '?kind=images&kind=videos',
        '?order=',
        '?order=latest',
        '?kind=',
        '?kind=video',
        '?tag=',
        '?unseen=true',
        '?fav=2',
        '?locked=',
        '?incomplete=-1',
    ],
)
async def test_invalid_filters_are_not_silently_dropped(
    http: _HTTPFixture, query: str
) -> None:
    response = await http.client.get(f'/api/authors/writer/posts{query}')
    error = api.ErrorResponse.model_validate(await response.json())
    assert response.status == 400
    assert error.error.code == 'invalid_query'


async def test_search_returns_plain_original_runs_and_tags_count_posts(
    http: _HTTPFixture,
) -> None:
    result = await _posts(http, '?q=script')
    text = next(row for row in result.rows if row.id == TEXT_ID)
    assert text.match is not None
    assert ''.join(run.text for run in text.match.title) == 'Всё <script> шейдеры'
    assert any(run.text == 'script' and run.matched for run in text.match.title)
    assert text.match.text is not None
    assert '<script>' in ''.join(run.text for run in text.match.text)
    response = await http.client.get('/api/authors/writer/tags')
    tags = TypeAdapter(list[api.TagCount]).validate_python(await response.json())
    assert {item.tag: item.count for item in tags} == {'Mix': 1, 'lesson': 1, 'text': 1}


@pytest.mark.parametrize('query', ['%22', 'AND', '*'])
async def test_operator_looking_search_remains_valid_text(
    http: _HTTPFixture, query: str
) -> None:
    result = await _posts(http, f'?q={query}')
    assert result.total == len(result.rows)


async def test_detail_retains_inventory_marks_and_removed_downloads(
    http: _HTTPFixture,
) -> None:
    detail = await _detail(http)
    assert detail.counts == api.MediaCounts(images=1, videos=1, files=1, audio=1)
    assert detail.missing_media == 2
    assert detail.seen
    assert detail.favorite
    assert detail.updated
    assert detail.tier_price_rub == 150.5
    assert detail.post_price_rub == 75.0
    assert detail.has_folder
    assert detail.tags == ['lesson', 'Mix', 'lesson']
    assert [item.kind for item in detail.media] == ['audio', 'files', 'videos']
    assert [item.removed for item in detail.media] == [False, True, True]
    assert detail.media[0].position_s == 34
    assert detail.media[0].duration_s == 90
    assert detail.media[0].filename == AUDIO_PATH.rsplit('/', 1)[1]
    assert len({item.id for item in detail.media}) == 3
    assert 'Removed by the author' in detail.body_html
    assert '&lt;script&gt;' in detail.body_html
    assert '<script>' not in detail.body_html


async def test_detail_and_list_derive_the_same_current_summary(
    http: _HTTPFixture,
) -> None:
    rows = {row.id: row for row in (await _posts(http)).rows}
    for post_id, row in rows.items():
        detail = await _detail(http, post_id)
        assert (
            api.PostRow.model_validate(
                detail.model_dump(include=set(api.PostRow.model_fields))
            )
            == row
        )


def _save_authored_links(library: ReadLibrary, hrefs: list[str]) -> None:
    library.record.blocks.insert(
        0,
        TextBlock(
            [
                PostDataChunkText.TextFragment(f'Link {index}', link_url=href)
                for index, href in enumerate(hrefs)
            ]
        ),
    )
    library.store.save_post(library.folder, library.record)


async def test_detail_links_resolve_full_ids_across_authors_without_saved_html(
    http: _HTTPFixture,
) -> None:
    first = make_record('eeeeeeee-first-full-id', 'Old title 100% #1')
    second = make_record('eeeeeeee-second-full-id', 'Another title')
    cross_author = make_record('99999999-other-author', 'Another author')
    cross_author.post.author = 'another_author'
    cross_author.post.url = (
        f'https://boosty.to/another_author/posts/{cross_author.post.id}'
    )
    for record in (first, second, cross_author):
        folder = save_record(http.library.root, http.library.store, record)
        assert not (http.library.root / folder / 'post.html').exists()
    http.library.reader.prepare()
    _save_authored_links(
        http.library,
        [
            first.post.url + '?mode=reader#lesson',
            second.post.url,
            cross_author.post.url,
        ],
    )
    before = _canonical_snapshot(http.library.root)

    detail = await _detail(http)

    assert f'href="/a/writer/p/{first.post.id}?mode=reader#lesson"' in detail.body_html
    assert f'href="/a/writer/p/{second.post.id}"' in detail.body_html
    assert f'href="/a/another_author/p/{cross_author.post.id}"' in detail.body_html
    assert _canonical_snapshot(http.library.root) == before


async def test_detail_resolves_targets_again_on_each_request(
    http: _HTTPFixture,
) -> None:
    target = make_record('ffffffff-later-target', 'Arrived later')
    _save_authored_links(http.library, [target.post.url])

    assert f'href="{target.post.url}"' in (await _detail(http)).body_html

    save_record(http.library.root, http.library.store, target)
    http.library.reader.prepare()

    assert f'href="/a/writer/p/{target.post.id}"' in (await _detail(http)).body_html


async def test_locked_target_links_require_a_retained_body(
    http: _HTTPFixture,
) -> None:
    retained = http.library.store.find_post('writer', TEXT_ID)
    assert retained is not None
    assert retained.record is not None
    http.library.store.save_locked_post(LockedPost(retained.record.post, NOW))
    http.library.reader.prepare()
    locked_url = f'https://boosty.to/writer/posts/{LOCKED_ID}'
    _save_authored_links(http.library, [locked_url, retained.record.post.url])

    detail = await _detail(http)

    assert f'href="{locked_url}"' in detail.body_html
    assert f'href="/a/writer/p/{TEXT_ID}"' in detail.body_html


async def test_only_authored_post_links_lookup_targets_in_the_worker_thread(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    target_url = f'https://boosty.to/writer/posts/{TEXT_ID}'
    _save_authored_links(
        http.library,
        [
            target_url,
            'https://example.com/lesson',
            '../manual.html',
            'javascript:run()',
        ],
    )
    loop_thread = threading.get_ident()
    calls: list[PostIdentity] = []
    original = http.library.reader.post_folder

    def lookup(author: str, post_id: str) -> str | None:
        assert threading.get_ident() != loop_thread
        calls.append(PostIdentity(author, post_id))
        return original(author, post_id)

    monkeypatch.setattr(http.library.reader, 'post_folder', lookup)

    detail = await _detail(http)

    assert calls == [PostIdentity('writer', TEXT_ID)]
    assert 'href="https://example.com/lesson"' in detail.body_html
    assert 'href="../manual.html"' in detail.body_html
    assert 'javascript:' not in detail.body_html
    assert f'href="{http.library.record.post.url}"' in detail.body_html


async def test_unreadable_link_target_preserves_the_readable_source(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    href = f'https://boosty.to/writer/posts/{TEXT_ID}'
    _save_authored_links(http.library, [href])

    def unreadable(author: str, post_id: str) -> str | None:
        del author, post_id
        message = '/private/library/target.json is corrupt'
        raise LibraryReadError(message)

    monkeypatch.setattr(http.library.reader, 'post_folder', unreadable)

    detail = await _detail(http)

    assert f'href="{href}"' in detail.body_html
    assert 'Saved body' in detail.body_html
    assert '/private/library' not in detail.body_html


async def test_locked_only_detail_has_remote_counts_and_no_missing_inventory(
    http: _HTTPFixture,
) -> None:
    detail = await _detail(http, LOCKED_ID)
    assert detail.access == 'locked'
    assert detail.body_html == ''
    assert detail.media == []
    assert not detail.has_folder
    assert detail.missing_media == 0
    assert detail.counts == api.MediaCounts(images=2, videos=3, files=4, audio=5)
    assert detail.cover_path == 'locked/teaser.jpg'


async def test_detail_reads_fresh_metadata_body_and_marks_once(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = http.library
    library.record.post.title = 'Fresh title'
    library.record.blocks.insert(
        0, TextBlock([PostDataChunkText.TextFragment('Fresh body')])
    )
    library.store.save_post(library.folder, library.record)
    JsonPostMarks(library.root).save_marks(
        'writer',
        POST_ID,
        PostMarks(seen_at=NOW, positions={AUDIO_ID: PlaybackPosition(80.0, NOW)}),
    )
    original = library.reader.post
    calls: list[str] = []

    def read(author: str, post_id: str) -> LibraryPostDetails | None:
        calls.append(post_id)
        return original(author, post_id)

    def forbidden(*args: object, **kwargs: object) -> None:
        del args, kwargs
        pytest.fail('Detail requested another snapshot or synchronized the index')

    monkeypatch.setattr(library.reader, 'post', read)
    for method in ('list_posts', 'get_marks', 'prepare'):
        monkeypatch.setattr(library.reader, method, forbidden)
    detail = await _detail(http)
    assert calls == [POST_ID]
    assert detail.title == 'Fresh title'
    assert 'Fresh body' in detail.body_html
    assert not detail.favorite
    assert not detail.updated
    assert detail.media[0].position_s == 80
    assert detail.media[0].finished


async def test_lost_access_keeps_saved_body_and_uses_fresh_locked_metadata(
    http: _HTTPFixture,
) -> None:
    library = http.library
    metadata = replace(
        library.record.post,
        title='Currently locked',
        tags=['new'],
        content_counters={'image': 99},
    )
    library.store.save_locked_post(LockedPost(metadata, NOW + timedelta(days=1)))
    detail = await _detail(http)
    assert detail.access == 'locked'
    assert detail.title == 'Currently locked'
    assert detail.tags == ['new']
    assert detail.has_folder
    assert 'Saved body' in detail.body_html
    assert detail.media[0].position_s == 34
    assert detail.counts.images == 1
    assert detail.missing_media == 2


async def test_unicode_media_paths_encode_once_and_support_range(
    http: _HTTPFixture,
) -> None:
    detail = await _detail(http)
    folder = http.library.folder.partition('/')[2]
    relative = f'{folder}/{AUDIO_PATH}'
    url = '/media/writer/' + quote(relative, safe='/')
    assert detail.media[0].path == relative
    assert url in detail.body_html
    assert '%2525' not in detail.body_html
    assert detail.cover_path == f'{folder}/{IMAGE_PATH}'
    response = await http.client.get(url, headers={'Range': 'bytes=2-5'})
    assert response.status == 206
    assert await response.read() == MEDIA_BYTES[2:6]
    assert response.headers['Content-Range'] == 'bytes 2-5/15'


@pytest.mark.skipif(
    os.name == 'nt', reason='Windows filenames cannot contain a question mark'
)
async def test_question_mark_in_a_media_filename_is_not_a_query(
    http: _HTTPFixture,
) -> None:
    path = 'audio/track?second.mp3'
    http.library.record.media[AUDIO_ID].path = path
    target = http.library.root / http.library.folder / path
    target.write_bytes(MEDIA_BYTES)
    http.library.store.save_post(http.library.folder, http.library.record)
    detail = await _detail(http)
    url = '/media/writer/' + quote(detail.media[0].path, safe='/')
    assert '%3F' in url
    assert url in detail.body_html
    response = await http.client.get(url)
    assert response.status == 200
    assert await response.read() == MEDIA_BYTES


@pytest.mark.parametrize('record_name', ['post.json', 'viewer.json'])
async def test_corrupt_canonical_data_is_an_explicit_private_error(
    http: _HTTPFixture, record_name: str
) -> None:
    path = http.library.root / http.library.folder / record_name
    path.write_bytes(b'{broken')
    response = await http.client.get(f'/api/authors/writer/posts/{POST_ID}')
    body = await response.text()
    error = api.ErrorResponse.model_validate_json(body)
    assert response.status == 409
    assert error.error.code == 'library_unavailable'
    assert str(http.library.root) not in body
    assert record_name not in body


async def test_missing_folder_returns_404_without_synchronizing_lists(
    http: _HTTPFixture,
) -> None:
    rmtree(http.library.root / http.library.folder)
    response = await http.client.get(f'/api/authors/writer/posts/{POST_ID}')
    assert response.status == 404
    assert POST_ID in [row.id for row in (await _posts(http)).rows]


async def test_missing_saved_folder_can_fall_back_to_a_fresh_locked_observation(
    http: _HTTPFixture,
) -> None:
    metadata = replace(
        http.library.record.post,
        title='Only the locked overview',
        content_counters={'audio': 4},
    )
    http.library.store.save_locked_post(LockedPost(metadata, NOW))
    rmtree(http.library.root / http.library.folder)
    detail = await _detail(http)
    assert detail.title == 'Only the locked overview'
    assert detail.access == 'locked'
    assert detail.body_html == ''
    assert detail.media == []
    assert not detail.has_folder
    assert not detail.favorite
    assert detail.counts == api.MediaCounts(audio=4)


async def test_changed_full_identity_is_not_returned_under_the_old_post_url(
    http: _HTTPFixture,
) -> None:
    record = replace(
        http.library.record,
        post=replace(http.library.record.post, id='bbbbbbbb-replacement'),
    )
    write_post_record(http.library.root / http.library.folder, record)
    response = await http.client.get(f'/api/authors/writer/posts/{POST_ID}')
    error = api.ErrorResponse.model_validate(await response.json())
    assert response.status == 409
    assert error.error.code == 'library_unavailable'


async def test_media_identity_distinguishes_the_same_key_in_two_posts(
    http: _HTTPFixture,
) -> None:
    record = make_record('ffffffff-second', 'Second track')
    record.media[AUDIO_ID] = replace(http.library.record.media[AUDIO_ID])
    save_record(http.library.root, http.library.store, record)
    http.library.reader.prepare()
    original = await _detail(http)
    another = await _detail(http, record.post.id)
    assert original.media[0].id != another.media[0].id
    assert original.media[0].post_id == POST_ID
    assert another.media[0].post_id == record.post.id


def _canonical_snapshot(root: Path) -> dict[str, _Fingerprint]:
    return {
        path.relative_to(root).as_posix(): _Fingerprint(
            path.stat().st_mtime_ns,
            sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob('*.json')
    }


async def test_concurrent_real_reader_requests_preserve_canonical_data(
    http: _HTTPFixture,
) -> None:
    before = _canonical_snapshot(http.library.root)
    paths = [
        '/api/authors',
        '/api/authors/writer',
        '/api/authors/writer/posts?q=shader',
        '/api/authors/writer/tags',
        f'/api/authors/writer/posts/{POST_ID}',
        '/media/writer/locked/teaser.jpg',
    ]

    async def request(path: str) -> None:
        async with http.client.get(path) as response:
            assert response.status == 200, await response.text()
            assert await response.read()

    await asyncio.gather(*(request(path) for _ in range(8) for path in paths))
    assert _canonical_snapshot(http.library.root) == before


async def test_slow_post_read_does_not_block_another_request(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = http.library.reader.post

    def slow_read(author: str, post_id: str) -> LibraryPostDetails | None:
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=10)
        return original(author, post_id)

    monkeypatch.setattr(http.library.reader, 'post', slow_read)
    slow = asyncio.ensure_future(
        http.client.get(f'/api/authors/writer/posts/{POST_ID}')
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        fast = await asyncio.wait_for(http.client.get('/api/authors'), timeout=1)
        assert fast.status == 200
        assert not slow.done()
        await fast.read()
        await asyncio.sleep(2)
        assert not slow.done()
    finally:
        release.set()
        response = await slow
        await response.read()
    assert response.status == 200
