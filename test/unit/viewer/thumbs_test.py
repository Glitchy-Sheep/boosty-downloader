"""Thumbnail HTTP selection, source freshness and local image boundaries."""

from __future__ import annotations

import asyncio
import errno
import os
import threading
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest
from aiohttp.test_utils import TestClient, TestServer
from support.viewer_read_library import (
    IMAGE_PATH,
    LOCKED_ID,
    NOW,
    POST_ID,
    ReadLibrary,
    make_library,
)
from yarl import URL

from boosty_downloader.application.post_body_renderer import StoredPostBodyRenderer
from boosty_downloader.domain.stored_post import (
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
)
from boosty_downloader.viewer.app import create_app
from boosty_downloader.viewer.media import image_file_response
from boosty_downloader.viewer.urls import media_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from aiohttp import ClientResponse, web

    from boosty_downloader.domain.library import LibraryPostDetails

THUMB = '.boosty-downloader/thumbs/cover.png'
BODY = b'0123456789-thumb'


@dataclass(frozen=True, slots=True)
class _Fixture:
    library: ReadLibrary
    client: TestClient[web.Request, web.Application]

    def save(self) -> None:
        self.library.store.save_post(self.library.folder, self.library.record)

    def write(self, relative: str, body: bytes = BODY) -> Path:
        path = self.library.root / 'writer' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def thumb(self) -> Path:
        self.library.record.media['image:cover'].thumbnail_path = THUMB
        self.save()
        return self.write(THUMB)

    def url(self, post_id: str = POST_ID) -> str:
        return f'/thumbs/writer/{post_id}'


@pytest.fixture
async def http(tmp_path: Path) -> AsyncIterator[_Fixture]:
    library = make_library(tmp_path / 'library')
    app = create_app(
        reader=library.reader,
        library_root=library.root,
        body_renderer=StoredPostBodyRenderer(),
    )
    async with TestClient(TestServer(app)) as client:
        yield _Fixture(library, client)


def _boundary(response: ClientResponse) -> None:
    assert response.headers['Cross-Origin-Resource-Policy'] == 'same-origin'
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert 'Content-Security-Policy' in response.headers
    assert not any(
        key.lower().startswith('access-control-') for key in response.headers
    )


async def test_image_without_thumbnail_redirects_once_to_encoded_original(
    http: _Fixture,
):
    entry = http.library.record.media['image:cover']
    entry.path = 'images/кадр 100% #?x=y&z=%2F.png'
    http.write(f'{http.library.folder.partition("/")[2]}/{entry.path}')
    http.save()
    response = await http.client.get(http.url(), allow_redirects=False)
    assert response.status == 302
    expected = media_url(
        'writer', f'{http.library.folder.partition("/")[2]}/{entry.path}'
    )
    assert response.headers['Location'] == expected
    assert '?embed=' not in expected
    _boundary(response)
    original = await http.client.get(URL(expected, encoded=True))
    assert original.status == 200
    assert await original.read() == BODY


async def test_thumbnail_has_media_mime_headers_ranges_and_conditional_support(
    http: _Fixture,
):
    path = http.thumb()
    path.with_suffix('.png.gz').write_bytes(b'wrong compressed sibling')
    response = await http.client.get(http.url(), headers={'Accept-Encoding': 'gzip'})
    assert response.status == 200
    assert await response.read() == BODY
    assert response.headers['Content-Type'] == 'image/png'
    assert 'Content-Encoding' not in response.headers
    _boundary(response)
    partial = await http.client.get(http.url(), headers={'Range': 'bytes=2-5'})
    assert partial.status == 206
    assert await partial.read() == BODY[2:6]
    _boundary(partial)
    unchanged = await http.client.get(
        http.url(), headers={'If-None-Match': response.headers['ETag']}
    )
    assert unchanged.status == 304
    _boundary(unchanged)
    head = await http.client.head(http.url())
    assert head.status == 200
    assert await head.read() == b''
    assert head.headers['Content-Length'] == str(len(BODY))


@pytest.mark.parametrize('status', [MediaStatus.downloaded, MediaStatus.deleted])
async def test_surviving_thumbnail_does_not_require_original(
    http: _Fixture, status: MediaStatus
):
    http.thumb()
    (http.library.root / http.library.folder / IMAGE_PATH).unlink()
    http.library.record.media['image:cover'].status = status
    http.save()
    response = await http.client.get(http.url())
    assert response.status == 200
    assert await response.read() == BODY


async def test_deleted_thumbnail_directory_falls_back_without_recreation(
    http: _Fixture,
):
    path = http.thumb()
    path.unlink()
    path.parent.rmdir()
    response = await http.client.get(http.url(), allow_redirects=False)
    assert response.status == 302
    assert not path.parent.exists()


async def test_missing_both_image_files_returns_404(http: _Fixture):
    http.library.record.media['image:cover'].thumbnail_path = THUMB
    http.save()
    (http.library.root / http.library.folder / IMAGE_PATH).unlink()
    response = await http.client.get(http.url())
    assert response.status == 404
    _boundary(response)


def _video(http: _Fixture, name: str = 'first', *, preview: bool = True) -> None:
    key = f'boosty_video:{name}'
    path = f'video/{name}.jpg' if preview else None
    http.library.record.media[key] = MediaEntry(
        MediaKind.boosty_video,
        MediaStatus.pending,
        NOW,
        20,
        preview_path=path,
    )
    http.library.record.blocks.append(MediaBlock(key))
    if path:
        http.write(f'{http.library.folder.partition("/")[2]}/{path}', name.encode())
    http.save()


async def test_new_image_arrival_replaces_video_cover_without_index_refresh(
    http: _Fixture,
):
    http.library.record.blocks.clear()
    _video(http)
    response = await http.client.get(http.url())
    assert await response.read() == b'first'
    http.library.record.blocks.append(MediaBlock('image:cover'))
    http.thumb()
    response = await http.client.get(http.url())
    assert await response.read() == BODY


@pytest.mark.parametrize('removed', [False, True])
async def test_removed_or_nonbody_images_cannot_be_cover(
    http: _Fixture, *, removed: bool
):
    http.thumb()
    http.library.record.blocks.clear()
    if removed:
        http.library.record.media['image:cover'].removed_at = NOW
        http.library.record.blocks.append(MediaBlock('image:cover'))
    _video(http)
    response = await http.client.get(http.url())
    assert response.status == 200
    assert await response.read() == b'first'
    assert response.headers['Content-Type'] == 'image/jpeg'


async def test_each_image_original_precedes_later_image_thumbnail(http: _Fixture):
    entry = replace(
        http.library.record.media['image:cover'], thumbnail_path=THUMB, position=0
    )
    http.library.record.media['image:second'] = entry
    http.library.record.blocks.append(MediaBlock('image:second'))
    http.write(THUMB)
    http.save()
    response = await http.client.get(http.url(), allow_redirects=False)
    assert response.status == 302
    http.library.record.blocks.insert(0, MediaBlock('image:second'))
    http.save()
    response = await http.client.get(http.url())
    assert response.status == 200
    assert await response.read() == BODY


async def test_only_first_current_boosty_preview_is_considered(http: _Fixture):
    http.library.record.blocks.clear()
    _video(http, preview=False)
    _video(http, 'second')
    response = await http.client.get(http.url())
    assert response.status == 404


async def test_external_video_preview_is_not_post_cover(http: _Fixture):
    http.library.record.blocks.clear()
    key = 'external_video:https://example.test/video'
    http.library.record.media[key] = MediaEntry(
        MediaKind.external_video,
        MediaStatus.pending,
        NOW,
        0,
        preview_path='external.jpg',
    )
    http.library.record.blocks.append(MediaBlock(key))
    http.write(f'{http.library.folder.partition("/")[2]}/external.jpg')
    http.save()
    assert (await http.client.get(http.url())).status == 404


@pytest.mark.parametrize('saved', [False, True])
async def test_locked_thumbnail_and_original_fallback(http: _Fixture, *, saved: bool):
    post_id = POST_ID if saved else LOCKED_ID
    detail = http.library.reader.post('writer', post_id)
    assert detail is not None
    if saved:
        http.library.record.blocks.clear()
        http.save()
    locked = LockedPost(detail.content.overview.post, NOW, 'locked/teaser.jpg', THUMB)
    http.library.store.save_locked_post(locked)
    path = http.write(THUMB)
    response = await http.client.get(http.url(post_id))
    assert response.status == 200
    assert await response.read() == BODY
    path.unlink()
    response = await http.client.get(http.url(post_id), allow_redirects=False)
    assert response.status == 302
    assert response.headers['Location'] == '/media/writer/locked/teaser.jpg'
    (http.library.root / 'writer/locked/teaser.jpg').unlink()
    assert (await http.client.get(http.url(post_id))).status == 404


@pytest.mark.parametrize(
    'url',
    [
        '/thumbs',
        '/thumbs/',
        '/thumbs/writer',
        '/thumbs/writer/unknown',
        '/thumbs/missing/post',
        '/thumbs/.boosty-downloader/post',
        '/thumbs/writer%2f..%2fother/post',
    ],
)
async def test_unknown_and_reserved_routes_never_serve_spa(http: _Fixture, url: str):
    response = await http.client.get(URL(url, encoded=True))
    assert response.status == 404
    _boundary(response)
    assert 'text/html' not in response.headers.get('Content-Type', '')


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('folder', 'empty/post'),
        ('folder', 'writer/../empty/post'),
        ('thumbnail_path', '../empty/private.jpg'),
        ('thumbnail_path', '/empty/private.jpg'),
        ('thumbnail_path', 'https://example.test/private.jpg'),
        ('thumbnail_path', 'C:/private.jpg'),
        ('thumbnail_path', r'..\empty\private.jpg'),
        ('thumbnail_path', '.boosty-downloader/thumbs/../private.jpg'),
        ('path', '../private.jpg'),
        ('path', 'https://example.test/private.jpg'),
    ],
)
async def test_untrusted_snapshot_paths_cannot_escape_author(
    http: _Fixture,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
):
    detail = http.library.reader.post('writer', POST_ID)
    assert detail is not None
    assert detail.content.record is not None
    entry = detail.content.record.media['image:cover']
    entry.path = None
    entry.thumbnail_path = None
    content = detail.content
    if field == 'folder':
        content = replace(content, folder=value)
        entry.thumbnail_path = THUMB
        http.write(THUMB)
    else:
        setattr(entry, field, value)
    detail = replace(detail, content=content)
    monkeypatch.setattr(http.library.reader, 'post', lambda *_: detail)
    response = await http.client.get(http.url(), allow_redirects=False)
    assert response.status == 404
    _boundary(response)


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as error:
        if (
            error.errno in {errno.EPERM, errno.EACCES, errno.ENOSYS}
            or getattr(error, 'winerror', None) == 1314
        ):
            pytest.skip('Filesystem does not permit symlinks')
        raise


@pytest.mark.parametrize('target', ['inside', 'cross_author', 'outside', 'html'])
async def test_thumbnail_links_use_resolved_author_boundary_and_type(
    http: _Fixture, target: str
):
    thumb = http.thumb()
    thumb.unlink()
    root = http.library.root
    targets = {
        'inside': root / 'writer/actual.jpg',
        'cross_author': root / 'empty/actual.jpg',
        'outside': root.parent / 'actual.jpg',
        'html': root / 'writer/actual.html',
    }
    destination = targets[target]
    destination.write_bytes(b'target')
    _symlink(thumb, destination)
    response = await http.client.get(http.url(), allow_redirects=False)
    if target == 'inside':
        assert response.status == 200
        assert response.headers['Content-Type'] == 'image/jpeg'
        assert await response.read() == b'target'
    else:
        assert response.status == 302
    _boundary(response)


@pytest.mark.parametrize('extension', ['html', 'svg', 'pdf', 'mp4', 'txt'])
async def test_nonimage_originals_are_not_redirected(http: _Fixture, extension: str):
    entry = http.library.record.media['image:cover']
    entry.path = f'images/not-image.{extension}'
    http.write(
        f'{http.library.folder.partition("/")[2]}/{entry.path}',
        b'<script>unsafe</script>',
    )
    http.save()
    assert (await http.client.get(http.url(), allow_redirects=False)).status == 404


@pytest.mark.skipif(os.name == 'nt', reason='POSIX named pipe')
async def test_special_thumbnail_is_rejected_without_opening(http: _Fixture):
    path = http.thumb()
    path.unlink()
    os.mkfifo(path)
    response = await asyncio.wait_for(
        http.client.get(http.url(), allow_redirects=False), timeout=2
    )
    assert response.status == 302


async def test_record_and_image_checks_run_off_the_event_loop(
    http: _Fixture, monkeypatch: pytest.MonkeyPatch
):
    http.thumb()
    thread = threading.get_ident()
    read = http.library.reader.post
    checks: list[str] = []

    def checked_read(author: str, post_id: str) -> LibraryPostDetails | None:
        assert threading.get_ident() != thread
        checks.append('record')
        return read(author, post_id)

    def checked_image(
        root: Path, author: str, relative: str
    ) -> web.FileResponse | None:
        assert threading.get_ident() != thread
        checks.append('image')
        return image_file_response(root, author, relative)

    monkeypatch.setattr(http.library.reader, 'post', checked_read)
    monkeypatch.setattr(
        'boosty_downloader.viewer.thumbs.image_file_response', checked_image
    )
    response = await http.client.get(http.url())
    assert response.status == 200
    assert checks == ['record', 'image']


async def test_thumbnail_prefix_is_reserved_without_a_library(tmp_path: Path):
    (tmp_path / 'index.html').write_text('SPA shell')
    async with TestClient(
        TestServer(create_app(reader=None, static_directory=tmp_path))
    ) as client:
        for url in ('/thumbs', '/thumbs/', '/thumbs/writer/post'):
            response = await client.get(url)
            assert response.status == 404
            assert 'SPA shell' not in await response.text()
            _boundary(response)


@pytest.mark.parametrize(
    'field', ['overview_author', 'overview_id', 'record_author', 'record_id']
)
async def test_snapshot_identity_must_match_request(
    http: _Fixture, monkeypatch: pytest.MonkeyPatch, field: str
):
    http.thumb()
    detail = http.library.reader.post('writer', POST_ID)
    assert detail is not None
    assert detail.content.record is not None
    content = detail.content
    if field.startswith('overview'):
        metadata = replace(content.overview.post)
        content = replace(content, overview=replace(content.overview, post=metadata))
    else:
        metadata = detail.content.record.post
    setattr(metadata, 'author' if field.endswith('author') else 'id', 'different')
    detail = replace(detail, content=content)
    monkeypatch.setattr(http.library.reader, 'post', lambda *_: detail)
    assert (await http.client.get(http.url(), allow_redirects=False)).status == 404


@pytest.mark.parametrize('alias', ['author', 'post_folder'])
async def test_directory_alias_does_not_gain_thumbnail_ownership(
    http: _Fixture, monkeypatch: pytest.MonkeyPatch, alias: str
):
    http.thumb()
    detail = http.library.reader.post('writer', POST_ID)
    assert detail is not None
    if alias == 'author':
        author_folder = http.library.root / 'writer'
        real_folder = http.library.root / 'real-writer'
        author_folder.rename(real_folder)
        _symlink(author_folder, real_folder, directory=True)
    else:
        folder = http.library.root / http.library.folder
        real_folder = folder.with_name(folder.name + '-real')
        folder.rename(real_folder)
        _symlink(folder, real_folder, directory=True)
    monkeypatch.setattr(http.library.reader, 'post', lambda *_: detail)
    response = await http.client.get(http.url(), allow_redirects=False)
    assert response.status == 404
    _boundary(response)


async def test_empty_thumbnail_falls_back_but_ordinary_media_keeps_empty_files(
    http: _Fixture,
):
    http.thumb().write_bytes(b'')
    response = await http.client.get(http.url(), allow_redirects=False)
    assert response.status == 302
    relative = f'{http.library.folder.partition("/")[2]}/{IMAGE_PATH}'
    assert response.headers['Location'] == media_url('writer', relative)
    _boundary(response)
    direct = await http.client.get(media_url('writer', THUMB))
    assert direct.status == 200
    assert await direct.read() == b''
    assert direct.headers['Content-Length'] == '0'


@pytest.mark.parametrize('has_video', [False, True])
async def test_empty_original_is_skipped_for_next_candidate_or_404(
    http: _Fixture, *, has_video: bool
):
    (http.library.root / http.library.folder / IMAGE_PATH).write_bytes(b'')
    if has_video:
        http.library.record.blocks.clear()
        http.library.record.blocks.append(MediaBlock('image:cover'))
        _video(http)
    response = await http.client.get(http.url(), allow_redirects=False)
    assert response.status == (200 if has_video else 404)
    if has_video:
        assert await response.read() == b'first'
    _boundary(response)


@pytest.mark.parametrize('has_teaser', [False, True])
async def test_empty_video_preview_falls_back_to_locked_teaser_or_404(
    http: _Fixture, *, has_teaser: bool
):
    http.library.record.blocks.clear()
    _video(http)
    http.write(f'{http.library.folder.partition("/")[2]}/video/first.jpg', b'')
    if has_teaser:
        http.library.store.save_locked_post(
            LockedPost(http.library.record.post, NOW, teaser_thumbnail_path=THUMB)
        )
        http.write(THUMB)
    response = await http.client.get(http.url(), allow_redirects=False)
    assert response.status == (200 if has_teaser else 404)
    if has_teaser:
        assert await response.read() == BODY
    _boundary(response)


async def test_empty_locked_teaser_thumbnail_uses_original_then_404(http: _Fixture):
    detail = http.library.reader.post('writer', LOCKED_ID)
    assert detail is not None
    http.library.store.save_locked_post(
        LockedPost(detail.content.overview.post, NOW, 'locked/teaser.jpg', THUMB)
    )
    http.write(THUMB, b'')
    response = await http.client.get(http.url(LOCKED_ID), allow_redirects=False)
    assert response.status == 302
    assert response.headers['Location'] == '/media/writer/locked/teaser.jpg'
    http.write('locked/teaser.jpg', b'')
    response = await http.client.get(http.url(LOCKED_ID), allow_redirects=False)
    assert response.status == 404
    _boundary(response)
