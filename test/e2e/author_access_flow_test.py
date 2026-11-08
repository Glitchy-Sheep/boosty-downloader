"""Author refresh and access observations across real HTTP download runs."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from e2e.download_flow_test import (
    AUTHOR,
    POST_DIR_NAME,
    _blob_body,
    _local_payload,
    _QuietReporter,
    _run_download,
)
from support.synthetic_blog import DESCRIPTION_TEXT, synthetic_blog
from support.synthetic_post import POST_ID, synthetic_post

from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_SERVICE_FOLDER,
    read_author_record,
    read_locked_posts,
)
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class _RemoteAuthor:
    blog: dict[str, Any] = field(default_factory=synthetic_blog)
    post: dict[str, Any] = field(default_factory=synthetic_post)
    extra_posts: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    avatar: bytes = b'first avatar'
    cover: bytes = b'first cover'
    blog_status: int = 200
    avatar_status: int = 200
    avatar_redirects: bool = False
    blog_requests: int = 0
    asset_requests: list[str] = field(default_factory=list[str])

    async def blog_info(self, request: web.Request) -> web.Response:
        self.blog_requests += 1
        if self.blog_status != 200:
            return web.Response(status=self.blog_status)
        return web.json_response(_local_payload(json.dumps(self.blog), request.host))

    async def listing(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                'data': [
                    _local_payload(json.dumps(post), request.host)
                    for post in [self.post, *self.extra_posts]
                ],
                'extra': {'offset': '', 'isLast': True},
            }
        )

    async def single_post(self, request: web.Request) -> web.Response:
        return web.json_response(_local_payload(json.dumps(self.post), request.host))

    async def asset(self, request: web.Request) -> web.Response:
        self.asset_requests.append(request.path)
        if request.path.endswith('avatar.png'):
            if self.avatar_redirects:
                raise web.HTTPFound(request.path)
            return web.Response(
                body=self.avatar, status=self.avatar_status, content_type='image/png'
            )
        return web.Response(body=self.cover, content_type='image/png')

    def app(self) -> web.Application:
        app = web.Application()
        app.router.add_get(f'/v1/blog/{AUTHOR}', self.blog_info)
        app.router.add_get(f'/v1/blog/{AUTHOR}/post/', self.listing)
        app.router.add_get(f'/v1/blog/{AUTHOR}/post/{POST_ID}', self.single_post)
        app.router.add_get('/blog/{name}', self.asset)
        app.router.add_get('/{tail:.*}', _media)
        return app


async def _media(request: web.Request) -> web.Response:
    return _blob_body(request.path)


@dataclass(frozen=True)
class _FileSnapshot:
    content: bytes
    modified_ns: int


def _snapshot(folder: Path) -> dict[str, _FileSnapshot]:
    return {
        path.relative_to(folder).as_posix(): _FileSnapshot(
            path.read_bytes(), path.stat().st_mtime_ns
        )
        for path in folder.rglob('*')
        if path.is_file()
    }


@pytest.fixture(params=[None, POST_ID], ids=['bulk', 'single'])
def post_id(request: pytest.FixtureRequest) -> str | None:
    value: str | None = request.param
    return value


async def test_each_run_refreshes_author_without_counting_its_images_as_post_media(
    tmp_path: Path,
    post_id: str | None,
) -> None:
    remote = _RemoteAuthor()
    async with TestServer(remote.app()) as server:
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), post_id=post_id
        )
        first = read_author_record(tmp_path, AUTHOR)
        assert first is not None
        assert first.description == DESCRIPTION_TEXT
        assert first.avatar_path == f'{AUTHOR_SERVICE_FOLDER}/avatar.png'
        assert first.cover_path == f'{AUTHOR_SERVICE_FOLDER}/cover.png'
        remote.blog['title'] = 'Renamed journal'
        remote.blog['count']['posts'] = 21
        remote.avatar = b'new avatar'
        remote.cover = b'new cover'
        stats = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), post_id=post_id
        )

    current = read_author_record(tmp_path, AUTHOR)
    assert current is not None
    assert current.avatar_path is not None
    assert current.cover_path is not None
    assert current.title == 'Renamed journal'
    assert current.remote_post_count == 21
    assert current.synced_at > first.synced_at
    assert (tmp_path / AUTHOR / current.avatar_path).read_bytes() == remote.avatar
    assert (tmp_path / AUTHOR / current.cover_path).read_bytes() == remote.cover
    assert remote.blog_requests == 2
    assert len(remote.asset_requests) == 4
    assert stats.media == MediaCounts()


@pytest.mark.parametrize('missing_url', [False, True], ids=['failed', 'missing'])
async def test_avatar_failure_or_missing_url_keeps_old_image_and_updates_cover(
    tmp_path: Path,
    *,
    missing_url: bool,
) -> None:
    remote = _RemoteAuthor()
    async with TestServer(remote.app()) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        first = read_author_record(tmp_path, AUTHOR)
        assert first is not None
        assert first.avatar_path is not None
        avatar = tmp_path / AUTHOR / first.avatar_path
        original = (avatar.read_bytes(), avatar.stat().st_mtime_ns)
        if missing_url:
            remote.blog['owner']['avatarUrl'] = None
        else:
            remote.avatar_status = 404
        remote.cover = b'changed cover'
        remote.blog['title'] = 'Updated metadata'
        reporter = _QuietReporter()
        await _run_download(tmp_path, server.make_url('/'), reporter)

    current = read_author_record(tmp_path, AUTHOR)
    assert current is not None
    assert current.cover_path is not None
    assert current.avatar_path == first.avatar_path
    assert current.title == 'Updated metadata'
    assert (avatar.read_bytes(), avatar.stat().st_mtime_ns) == original
    assert (tmp_path / AUTHOR / current.cover_path).read_bytes() == remote.cover
    image_warnings = [
        message
        for message in reporter.warnings
        if 'Could not refresh author avatar' in message
    ]
    assert bool(image_warnings) is not missing_url


async def test_failed_blog_lookup_preserves_author_and_still_updates_posts(
    tmp_path: Path,
) -> None:
    remote = _RemoteAuthor()
    async with TestServer(remote.app()) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        folder = tmp_path / AUTHOR / AUTHOR_SERVICE_FOLDER
        original = _snapshot(folder)
        remote.blog_status = 404
        remote.post['title'] = 'Updated post while blog metadata is unavailable'
        reporter = _QuietReporter()
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)

    assert _snapshot(folder) == original
    assert stats.posts_downloaded == 1
    assert any(
        'Could not refresh author details' in warning for warning in reporter.warnings
    )
    record = json.loads((tmp_path / AUTHOR / POST_DIR_NAME / 'post.json').read_bytes())
    assert record['post']['title'] == remote.post['title']


@pytest.mark.parametrize('excluded', [False, True])
async def test_locked_post_is_observed_without_creating_a_post_folder(
    tmp_path: Path,
    post_id: str | None,
    *,
    excluded: bool,
) -> None:
    remote = _RemoteAuthor()
    remote.post.update(hasAccess=False, data=[])
    async with TestServer(remote.app()) as server:
        await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            excluded_tags=('fixture',) if excluded else (),
            post_id=post_id,
        )

    locked = read_locked_posts(tmp_path, AUTHOR)
    assert set(locked) == {POST_ID}
    assert locked[POST_ID].post.title == remote.post['title']
    assert locked[POST_ID].teaser_path is None
    assert not (tmp_path / AUTHOR / POST_DIR_NAME).exists()


async def test_losing_and_regaining_access_preserves_saved_content_and_marks(
    tmp_path: Path,
    post_id: str | None,
) -> None:
    remote = _RemoteAuthor()
    async with TestServer(remote.app()) as server:
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), post_id=post_id
        )
        folder = tmp_path / AUTHOR / POST_DIR_NAME
        (folder / 'viewer.json').write_bytes(b'{"favorite": true}')
        original = _snapshot(folder)
        remote.post.update(hasAccess=False, data=[], title='New locked title')
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), post_id=post_id
        )
        assert _snapshot(folder) == original
        assert POST_ID in read_locked_posts(tmp_path, AUTHOR)
        remote.post['hasAccess'] = True
        await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            excluded_tags=('fixture',),
            post_id=post_id,
        )

    assert read_locked_posts(tmp_path, AUTHOR) == {}
    assert _snapshot(folder) == original


async def test_avatar_redirect_loop_does_not_block_cover_or_post_updates(
    tmp_path: Path,
) -> None:
    remote = _RemoteAuthor()
    async with TestServer(remote.app()) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        first = read_author_record(tmp_path, AUTHOR)
        assert first is not None
        assert first.avatar_path is not None
        avatar = tmp_path / AUTHOR / first.avatar_path
        original = _FileSnapshot(avatar.read_bytes(), avatar.stat().st_mtime_ns)
        remote.avatar_redirects = True
        remote.cover = b'updated cover despite the avatar failure'
        remote.post['title'] = 'Post updated after the avatar failure'
        reporter = _QuietReporter()
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)

    current = read_author_record(tmp_path, AUTHOR)
    assert current is not None
    assert current.cover_path is not None
    assert current.avatar_path == first.avatar_path
    assert _FileSnapshot(avatar.read_bytes(), avatar.stat().st_mtime_ns) == original
    assert (tmp_path / AUTHOR / current.cover_path).read_bytes() == remote.cover
    assert stats.posts_downloaded == 1
    assert any(
        'Could not refresh author avatar' in message for message in reporter.warnings
    )
    record = json.loads((tmp_path / AUTHOR / POST_DIR_NAME / 'post.json').read_bytes())
    assert record['post']['title'] == remote.post['title']


async def test_newly_accessible_post_downloads_its_full_content(
    tmp_path: Path,
    post_id: str | None,
) -> None:
    remote = _RemoteAuthor()
    remote.post.update(hasAccess=False, data=[])
    async with TestServer(remote.app()) as server:
        await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), post_id=post_id
        )
        assert POST_ID in read_locked_posts(tmp_path, AUTHOR)
        assert not (tmp_path / AUTHOR / POST_DIR_NAME).exists()
        remote.post = synthetic_post()
        stats = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), post_id=post_id
        )

    assert read_locked_posts(tmp_path, AUTHOR) == {}
    assert stats.posts_downloaded == 1
    assert (tmp_path / AUTHOR / POST_DIR_NAME / 'post.html').is_file()
    located = JsonPostStore(tmp_path).find_post(AUTHOR, POST_ID)
    assert located is not None
    assert located.record is not None
    downloaded = [
        piece
        for piece in located.record.media.values()
        if piece.status is MediaStatus.downloaded
    ]
    assert len(downloaded) == 4
    for piece in downloaded:
        assert piece.path is not None
        assert (tmp_path / located.folder / piece.path).is_file()


async def test_mixed_listing_refreshes_author_once_and_counts_locked_posts(
    tmp_path: Path,
) -> None:
    remote = _RemoteAuthor()
    locked = deepcopy(remote.post)
    locked_id = '90000000-0000-4000-8000-000000000001'
    locked.update(id=locked_id, hasAccess=False, data=[])
    remote.extra_posts.append(locked)
    async with TestServer(remote.app()) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())

    assert remote.blog_requests == 1
    assert len(remote.asset_requests) == 2
    assert stats.posts_locked == 1
    assert stats.posts_downloaded == 1
    assert set(read_locked_posts(tmp_path, AUTHOR)) == {locked_id}
    assert JsonPostStore(tmp_path).find_post(AUTHOR, locked_id) is None
