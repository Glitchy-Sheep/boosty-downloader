"""Only a local viewer page can open recorded media or real post folders."""

from __future__ import annotations

import asyncio
import os
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from multidict import CIMultiDict
from support.viewer_read_library import (
    AUDIO_ID,
    AUDIO_PATH,
    IMAGE_PATH,
    LOCKED_ID,
    NOW,
    POST_ID,
    ReadLibrary,
    make_library,
)

from boosty_downloader.application.post_body_renderer import StoredPostBodyRenderer
from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.stored_post import (
    LockedPost,
    MediaEntry,
    MediaKind,
    MediaStatus,
)
from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.app import create_app
from boosty_downloader.viewer.media_identity import media_identity
from boosty_downloader.viewer.opener import NO_OPENER, Opener, OpenError

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator
    from pathlib import Path

    from aiohttp import ClientResponse


@dataclass(frozen=True, slots=True)
class _HTTPFixture:
    library: ReadLibrary
    client: TestClient[web.Request, web.Application]
    opened: list[Path]
    revealed: list[Path]


@asynccontextmanager
async def _client(
    library: ReadLibrary, opener: Opener
) -> AsyncGenerator[TestClient[web.Request, web.Application], None]:
    app = create_app(
        reader=library.reader,
        library_root=library.root,
        body_renderer=StoredPostBodyRenderer(),
        opener=opener,
    )
    async with TestClient(TestServer(app)) as client:
        yield client


@pytest.fixture
async def http(tmp_path: Path) -> AsyncIterator[_HTTPFixture]:
    library = make_library(tmp_path / 'library')
    opened: list[Path] = []
    revealed: list[Path] = []
    opener = Opener(
        open=opened.append, reveal=revealed.append, folders=True, system='macos'
    )
    async with _client(library, opener) as client:
        yield _HTTPFixture(library, client, opened, revealed)


def _headers(client: TestClient[web.Request, web.Application]) -> dict[str, str]:
    return {
        'Origin': f'http://127.0.0.1:{client.port}',
        'Sec-Fetch-Site': 'same-origin',
    }


def _media_route(
    media_id: str = AUDIO_ID, *, post_id: str = POST_ID, author: str = 'writer'
) -> str:
    identity = media_identity(post_id, media_id)
    return f'/api/authors/{author}/media/{identity}/open'


def _post_route(post_id: str = POST_ID, *, author: str = 'writer') -> str:
    return f'/api/authors/{author}/posts/{post_id}/open'


async def _open(
    http: _HTTPFixture, media_id: str = AUDIO_ID, *, reveal: bool = False
) -> ClientResponse:
    return await http.client.post(
        _media_route(media_id), json={'reveal': reveal}, headers=_headers(http.client)
    )


async def _error(response: ClientResponse, status: int) -> api.ErrorBody:
    assert response.status == status, await response.text()
    return api.ErrorResponse.model_validate(await response.json()).error


def _save_file(http: _HTTPFixture, media_id: str, filename: str) -> Path:
    path = http.library.root / http.library.folder / 'files' / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'harmless fixture')
    http.library.record.media[media_id] = MediaEntry(
        MediaKind.file,
        MediaStatus.downloaded,
        NOW,
        len(http.library.record.media),
        path=f'files/{filename}',
        size=16,
    )
    http.library.store.save_post(http.library.folder, http.library.record)
    http.library.reader.prepare()
    return path.resolve()


async def test_capabilities_are_local_private_and_never_cached(
    http: _HTTPFixture,
) -> None:
    response = await http.client.get('/api/opener')
    assert response.status == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert api.OpenerCapabilities.model_validate(
        await response.json()
    ) == api.OpenerCapabilities(
        open=True,
        reveal=True,
        folders=True,
        system='macos',
        root=str(http.library.root.resolve()),
        sep=os.sep,
    )


async def test_no_reader_has_disabled_capabilities() -> None:
    async with TestClient(TestServer(create_app(reader=None))) as client:
        response = await client.get('/api/opener')
        assert response.status == 200
        assert response.headers['Cache-Control'] == 'no-store'
        assert api.OpenerCapabilities.model_validate(
            await response.json()
        ) == api.OpenerCapabilities(
            open=False,
            reveal=False,
            folders=False,
            sep=os.sep,
        )


async def test_media_and_post_actions_use_exact_absolute_paths(
    http: _HTTPFixture,
) -> None:
    assert (await _open(http)).status == 204
    assert (await _open(http, reveal=True)).status == 204
    response = await http.client.post(
        _post_route(), json={}, headers=_headers(http.client)
    )
    assert response.status == 204
    folder = (http.library.root / http.library.folder).resolve()
    assert http.opened == [folder / AUDIO_PATH, folder]
    assert http.revealed == [folder / AUDIO_PATH]


@pytest.mark.parametrize(
    'filename', ['пособие, часть 1.pdf', 'installer.exe', 'script.sh', 'no-suffix']
)
async def test_every_recorded_file_type_reaches_the_injected_opener(
    http: _HTTPFixture, filename: str
) -> None:
    path = _save_file(http, 'file:local', filename)
    assert (await _open(http, 'file:local')).status == 204
    assert http.opened == [path]


async def test_retained_removed_and_locked_media_remain_openable(
    http: _HTTPFixture,
) -> None:
    http.library.store.save_locked_post(LockedPost(http.library.record.post, NOW))
    http.library.reader.prepare()
    assert (await _open(http, 'file:removed')).status == 204
    assert (await _open(http)).status == 204
    response = await http.client.post(
        _post_route(), json={}, headers=_headers(http.client)
    )
    assert response.status == 204
    assert len(http.opened) == 3


@pytest.mark.parametrize(
    'media_id', ['absent', 'file:failed', 'file:never', 'boosty_video:pending']
)
async def test_missing_or_not_downloaded_media_is_not_found(
    http: _HTTPFixture, media_id: str
) -> None:
    error = await _error(await _open(http, media_id), 404)
    assert error.code == 'not_found'
    assert not http.opened


@pytest.mark.parametrize(
    'route',
    [
        _media_route(author='unknown'),
        _media_route(post_id='bbbbbbbb-another'),
        _post_route('unknown'),
        _post_route(LOCKED_ID),
    ],
)
async def test_unknown_resources_do_not_expose_local_paths(
    http: _HTTPFixture, route: str
) -> None:
    body = {'reveal': False} if '/media/' in route else {}
    response = await http.client.post(route, json=body, headers=_headers(http.client))
    error = await _error(response, 404)
    assert str(http.library.root) not in error.message
    assert not http.opened


@pytest.mark.parametrize('directory', [False, True])
async def test_missing_files_and_directories_are_not_opened_as_media(
    http: _HTTPFixture, *, directory: bool
) -> None:
    path = http.library.root / http.library.folder / AUDIO_PATH
    path.unlink()
    if directory:
        path.mkdir()
    await _error(await _open(http), 404)
    assert not http.opened


@pytest.mark.parametrize(
    ('target_name', 'expected_status'), [('actual.png', 204), ('install.sh', 403)]
)
async def test_contained_media_links_compare_stored_and_target_types(
    http: _HTTPFixture, target_name: str, expected_status: int
) -> None:
    image = http.library.root / http.library.folder / IMAGE_PATH
    target = image.parent / target_name
    target.write_bytes(b'harmless fixture')
    image.unlink()
    image.symlink_to(target)
    opened = await _open(http, 'image:cover')
    assert opened.status == expected_status
    assert (await _open(http, 'image:cover', reveal=True)).status == 204
    assert http.revealed == [target.resolve()]
    if expected_status == 403:
        assert (await _error(opened, 403)).code == 'open_not_allowed'
        assert not http.opened
    else:
        assert http.opened == [target.resolve()]


@pytest.mark.parametrize('missing', [False, True])
async def test_escaping_and_dangling_media_links_are_not_found(
    http: _HTTPFixture, *, missing: bool
) -> None:
    path = http.library.root / http.library.folder / AUDIO_PATH
    target = http.library.root.parent / 'outside.mp3'
    if not missing:
        target.write_bytes(b'outside')
    path.unlink()
    path.symlink_to(target)
    await _error(await _open(http), 404)
    await _error(await _open(http, reveal=True), 404)
    assert not http.opened
    assert not http.revealed


async def test_post_folder_links_are_not_opened_or_advertised(
    http: _HTTPFixture,
) -> None:
    folder = http.library.root / http.library.folder
    target = folder.with_name('retained-folder')
    folder.rename(target)
    folder.symlink_to(target, target_is_directory=True)
    response = await http.client.post(
        _post_route(), json={}, headers=_headers(http.client)
    )
    await _error(response, 404)
    detail = await http.client.get(f'/api/authors/writer/posts/{POST_ID}')
    assert detail.status == 200
    assert not (await detail.json())['has_folder']
    assert not http.opened


@pytest.mark.parametrize(
    'body',
    [
        {},
        {'reveal': 1},
        {'reveal': 'false'},
        {'reveal': None},
        {'reveal': False, 'path': '/private/file'},
        [],
        None,
    ],
)
async def test_media_body_is_strict(http: _HTTPFixture, body: object) -> None:
    response = await http.client.post(
        _media_route(),
        json=body,
        headers={**_headers(http.client), 'Content-Type': 'application/json'},
    )
    assert (await _error(response, 400)).code == 'invalid_request'
    assert not http.opened


@pytest.mark.parametrize(
    'body', [{'reveal': False}, {'path': '/private/file'}, [], None]
)
async def test_post_body_must_be_an_empty_object(
    http: _HTTPFixture, body: object
) -> None:
    response = await http.client.post(
        _post_route(),
        json=body,
        headers={**_headers(http.client), 'Content-Type': 'application/json'},
    )
    await _error(response, 400)
    assert not http.opened


@pytest.mark.parametrize('payload', [b'', b'{', b'\xff', b'{"reveal": NaN}'])
async def test_malformed_media_json_is_rejected(
    http: _HTTPFixture, payload: bytes
) -> None:
    response = await http.client.post(
        _media_route(),
        data=payload,
        headers={**_headers(http.client), 'Content-Type': 'application/json'},
    )
    await _error(response, 400)


async def test_malformed_identity_and_queries_are_rejected(http: _HTTPFixture) -> None:
    response = await http.client.post(
        '/api/authors/writer/media/not-an-identity/open',
        json={'reveal': False},
        headers=_headers(http.client),
    )
    await _error(response, 400)
    response = await http.client.post(
        _media_route() + '?path=elsewhere',
        json={'reveal': False},
        headers=_headers(http.client),
    )
    await _error(response, 400)
    await _error(await http.client.get('/api/opener?author=writer'), 400)
    await _error(await http.client.get('/api/opener', data=b'{}'), 400)


@pytest.mark.parametrize(
    'header',
    [
        'Forwarded',
        'X-Forwarded-For',
        'X-Forwarded-Host',
        'X-Forwarded-Unknown',
        'X-Real-IP',
        'X-Client-IP',
        'X-Cluster-Client-IP',
        'Via',
        'CF-Connecting-IP',
        'True-Client-IP',
        'Fastly-Client-IP',
    ],
)
async def test_any_proxy_header_disables_actions_and_paths(
    http: _HTTPFixture, header: str
) -> None:
    response = await http.client.get('/api/opener', headers={header: ''})
    capabilities = api.OpenerCapabilities.model_validate(await response.json())
    assert not capabilities.open
    assert not capabilities.reveal
    assert not capabilities.folders
    assert capabilities.root is None
    assert capabilities.system is None
    response = await http.client.post(
        _media_route(),
        json={'reveal': False},
        headers={**_headers(http.client), header: ''},
    )
    await _error(response, 403)
    assert not http.opened


@pytest.mark.parametrize(
    'headers',
    [
        {},
        {'Origin': 'null'},
        {'Origin': 'https://foreign.example'},
        {'Origin': 'http://localhost:9'},
        {'Sec-Fetch-Site': 'cross-site'},
    ],
)
async def test_open_requires_the_viewer_origin(
    http: _HTTPFixture, headers: dict[str, str]
) -> None:
    response = await http.client.post(
        _media_route(), json={'reveal': False}, headers=headers
    )
    await _error(response, 403)
    assert not http.opened


async def test_duplicate_origin_and_foreign_capability_metadata_disclose_no_paths(
    http: _HTTPFixture,
) -> None:
    headers = CIMultiDict(_headers(http.client))
    headers.add('Origin', headers['Origin'])
    response = await http.client.post(
        _media_route(), json={'reveal': False}, headers=headers
    )
    await _error(response, 403)
    for values in (
        headers,
        {'Origin': 'null'},
        {'Origin': 'https://foreign.example'},
        {'Sec-Fetch-Site': 'cross-site'},
    ):
        response = await http.client.get('/api/opener', headers=values)
        capabilities = api.OpenerCapabilities.model_validate(await response.json())
        assert capabilities.root is None
        assert not capabilities.open
    assert not http.opened


async def test_plain_text_write_is_refused(http: _HTTPFixture) -> None:
    response = await http.client.post(
        _media_route(), data='{"reveal":false}', headers=_headers(http.client)
    )
    await _error(response, 403)


async def test_foreign_host_is_refused_before_capabilities_or_actions(
    http: _HTTPFixture,
) -> None:
    headers = {'Host': 'foreign.example', 'Origin': 'http://foreign.example'}
    response = await http.client.get('/api/opener', headers=headers)
    assert (await _error(response, 421)).code == 'host_not_allowed'
    response = await http.client.post(
        _media_route(), json={'reveal': False}, headers=headers
    )
    await _error(response, 421)
    assert not http.opened


async def test_missing_post_folder_is_not_opened(http: _HTTPFixture) -> None:
    folder = http.library.root / http.library.folder
    folder.rename(folder.with_name('moved-post'))
    response = await http.client.post(
        _post_route(), json={}, headers=_headers(http.client)
    )
    await _error(response, 404)
    assert not http.opened


async def test_machine_name_allows_browsing_without_local_actions(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        'boosty_downloader.viewer.guard.socket.gethostname', lambda: 'desk.local'
    )
    headers = {
        'Host': f'desk.local:{http.client.port}',
        'Origin': f'http://desk.local:{http.client.port}',
    }
    assert (await http.client.get('/api/authors', headers=headers)).status == 200
    response = await http.client.get('/api/opener', headers=headers)
    assert (await response.json())['root'] is None
    response = await http.client.post(
        _media_route(), json={'reveal': False}, headers=headers
    )
    await _error(response, 403)
    assert not http.opened


async def test_remote_peer_receives_no_paths_or_actions(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web.Request, 'remote', property(lambda _self: '192.0.2.80'))
    capabilities = await (await http.client.get('/api/opener')).json()
    assert capabilities['root'] is None
    assert not capabilities['open']
    await _error(await _open(http), 403)
    assert not http.opened


async def test_no_opener_and_termux_capabilities_match_available_actions(
    tmp_path: Path,
) -> None:
    library = make_library(tmp_path / 'library')
    async with _client(library, NO_OPENER) as client:
        response = await client.get('/api/opener')
        assert api.OpenerCapabilities.model_validate(
            await response.json()
        ) == api.OpenerCapabilities(open=False, reveal=False, folders=False, sep=os.sep)
        response = await client.post(
            _media_route(), json={'reveal': False}, headers=_headers(client)
        )
        await _error(response, 403)
    opened: list[Path] = []
    async with _client(
        library,
        Opener(open=opened.append, reveal=None, folders=False, system='android'),
    ) as client:
        capabilities = await (await client.get('/api/opener')).json()
        assert capabilities['open']
        assert not capabilities['reveal']
        assert not capabilities['folders']
        assert capabilities['system'] == 'android'
        assert (
            await client.post(
                _media_route(), json={'reveal': False}, headers=_headers(client)
            )
        ).status == 204
        await _error(
            await client.post(
                _media_route(), json={'reveal': True}, headers=_headers(client)
            ),
            403,
        )
        await _error(
            await client.post(_post_route(), json={}, headers=_headers(client)), 403
        )
    assert len(opened) == 1


async def test_opener_failure_returns_its_reason(tmp_path: Path) -> None:
    library = make_library(tmp_path / 'library')

    def fail(path: Path) -> None:
        del path
        message = 'No application can open this file.'
        raise OpenError(message)

    async with _client(library, Opener(open=fail, reveal=fail, folders=True)) as client:
        response = await client.post(
            _media_route(), json={'reveal': False}, headers=_headers(client)
        )
        error = await _error(response, 409)
        assert error.code == 'open_failed'
        assert error.message == 'No application can open this file.'


async def test_corrupt_index_error_does_not_disclose_paths(
    http: _HTTPFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(*args: object) -> str:
        del args
        raise LibraryReadError(str(http.library.root))

    monkeypatch.setattr(http.library.reader, 'media_path', fail)
    error = await _error(await _open(http), 409)
    assert error.code == 'library_unavailable'
    assert str(http.library.root) not in error.message
    assert not http.opened


async def test_parallel_requests_each_complete_one_action(http: _HTTPFixture) -> None:
    responses = await asyncio.gather(
        *(_open(http, reveal=number % 2 == 1) for number in range(80))
    )
    assert all(response.status == 204 for response in responses)
    expected = (http.library.root / http.library.folder / AUDIO_PATH).resolve()
    assert http.opened == [expected] * 40
    assert http.revealed == [expected] * 40


async def test_slow_opener_does_not_block_reads(tmp_path: Path) -> None:
    library = make_library(tmp_path / 'library')
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def slow(path: Path) -> None:
        del path
        loop.call_soon_threadsafe(started.set)
        assert release.wait(timeout=10)

    async with _client(library, Opener(open=slow, reveal=slow, folders=True)) as client:
        pending = asyncio.ensure_future(
            client.post(
                _media_route(), json={'reveal': False}, headers=_headers(client)
            )
        )
        try:
            await asyncio.wait_for(started.wait(), timeout=5)
            response = await asyncio.wait_for(client.get('/api/authors'), timeout=2)
            assert response.status == 200
            await response.read()
            assert not pending.done()
        finally:
            release.set()
            response = await pending
            await response.read()
        assert response.status == 204
