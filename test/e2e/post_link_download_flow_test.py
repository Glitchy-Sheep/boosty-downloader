"""Local post links follow completed downloads without unnecessary page writes."""

from __future__ import annotations

import io
import logging
import posixpath
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient
from e2e.download_flow_test import (
    AUTHOR,
    _build_app,  # pyright: ignore[reportPrivateUsage]
    _dry_run,  # pyright: ignore[reportPrivateUsage]
    _QuietReporter,  # pyright: ignore[reportPrivateUsage]
    _run_download,  # pyright: ignore[reportPrivateUsage]
)
from rich.console import Console
from support.synthetic_post import (
    POST_ID,
    block_end,
    file_chunk,
    synthetic_post,
    text_chunk,
)

from boosty_downloader.application import post_pages as post_pages_module
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationTooManyFailuresError,
)
from boosty_downloader.application.filtering import VideoQualityOption
from boosty_downloader.application.post_download_state import PostDownloadState
from boosty_downloader.application.post_pages import prepare_post_page
from boosty_downloader.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.cli.commands import download as download_command
from boosty_downloader.cli.composition_root import App, AppSettings
from boosty_downloader.cli.console_progress_reporter import ConsoleProgressReporter
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post_folder import compose_post_directory_name
from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPIClient,
    BoostyAPIError,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Awaitable, Callable
    from pathlib import Path
    from typing import Any

    from yarl import URL

    from boosty_downloader.application.run_statistics import RunStatistics

SOURCE_ID = POST_ID
TARGET_ID = '10000000-0000-4000-8000-000000000002'
LINK_SUFFIX = '?from=lesson#chapter'
TARGET_URL = f'https://boosty.to/{AUTHOR}/posts/{TARGET_ID}{LINK_SUFFIX}'


@dataclass(frozen=True, slots=True)
class _FileState:
    content: bytes
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _FutureTarget:
    folder: str

    def post_folder(self, author: str, post_id: str) -> str | None:
        if author == AUTHOR and post_id == TARGET_ID:
            return self.folder
        return None


def _state(path: Path) -> _FileState:
    return _FileState(path.read_bytes(), path.stat().st_mtime_ns)


def _post(post_id: str, *, link: str | None = None) -> dict[str, Any]:
    payload = synthetic_post()
    chunk = text_chunk('Related lesson' if link else 'Saved lesson')
    if link is not None:
        chunk.update(type='link', url=link, explicit=True)
    payload.update(
        id=post_id,
        title='Source lesson' if post_id == SOURCE_ID else f'Target {post_id}',
        data=[chunk, block_end()],
        contentCounters={'text': 1},
    )
    return payload


def _app(
    posts: list[dict[str, Any]],
    *,
    fail_next_page: bool = False,
    next_posts: list[dict[str, Any]] | None = None,
) -> web.Application:
    app = _build_app([], payload=posts[0])
    prefix = f'/v1/blog/{AUTHOR}/post/'

    @web.middleware
    async def serve_posts(
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if request.path == prefix:
            if request.query.get('offset'):
                if next_posts is None:
                    return web.Response(status=500)
                return _listing_page(next_posts)
            return _listing_page(
                posts, has_next=fail_next_page or next_posts is not None
            )
        for post in posts:
            if request.path == prefix + post['id']:
                return web.json_response(post)
        return await handler(request)

    app.middlewares.append(serve_posts)
    return app


def _listing_page(
    posts: list[dict[str, Any]], *, has_next: bool = False
) -> web.Response:
    return web.json_response(
        {
            'data': posts,
            'extra': {'offset': 'next' if has_next else '', 'isLast': not has_next},
        }
    )


def _page(root: Path, post_id: str) -> Path:
    located = JsonPostStore(root).find_post(AUTHOR, post_id)
    assert located is not None
    assert located.record is not None
    return root / located.folder / 'post.html'


def _local_link(root: Path) -> str:
    source = _page(root, SOURCE_ID)
    target = _page(root, TARGET_ID)
    relative = posixpath.relpath(target.as_posix(), source.parent.as_posix())
    return quote(relative, safe='/') + LINK_SUFFIX


def _assert_link(root: Path, href: str) -> None:
    html = _page(root, SOURCE_ID).read_text(encoding='utf-8')
    assert f'href="{href}"' in html


@pytest.mark.parametrize('target_first', [False, True])
async def test_first_download_resolves_links_and_counts_each_post_once(
    tmp_path: Path, *, target_first: bool
) -> None:
    posts = [_post(SOURCE_ID, link=TARGET_URL), _post(TARGET_ID)]
    if target_first:
        posts.reverse()
    async with TestServer(_app(posts)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    _assert_link(tmp_path, _local_link(tmp_path))
    assert stats.posts_downloaded == 2
    assert stats.posts_cached == stats.posts_failed == 0


async def test_first_download_resolves_a_cycle_without_duplicate_counts(
    tmp_path: Path,
) -> None:
    source_url = f'https://boosty.to/{AUTHOR}/posts/{SOURCE_ID}'
    posts = [_post(SOURCE_ID, link=TARGET_URL), _post(TARGET_ID, link=source_url)]
    async with TestServer(_app(posts)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    _assert_link(tmp_path, _local_link(tmp_path))
    target_html = _page(tmp_path, TARGET_ID).read_text(encoding='utf-8')
    back_link = posixpath.relpath(
        _page(tmp_path, SOURCE_ID).as_posix(),
        _page(tmp_path, TARGET_ID).parent.as_posix(),
    )
    assert f'href="{quote(back_link, safe="/")}"' in target_html
    assert stats.posts_downloaded == 2
    assert stats.posts_cached == stats.posts_failed == 0


@pytest.mark.parametrize('cached', [False, True])
@pytest.mark.parametrize('cross_page', [False, True])
async def test_repeated_full_ids_keep_the_first_content_tags_and_access(
    tmp_path: Path, *, cached: bool, cross_page: bool
) -> None:
    source = _post(SOURCE_ID, link=TARGET_URL)
    target = _post(TARGET_ID)
    source_before = None
    if cached:
        async with TestServer(_app([source, target])) as server:
            await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        source_before = _state(_page(tmp_path, SOURCE_ID))
    excluded_id = '20000000-0000-4000-8000-000000000003'
    locked_id = '30000000-0000-4000-8000-000000000004'
    excluded = _post(excluded_id)
    excluded['tags'] = [{'title': 'skip'}]
    locked = _post(locked_id)
    locked['hasAccess'] = False
    first_posts = [source, target, excluded, locked]
    replacement = _post(SOURCE_ID)
    replacement['title'] = 'Later metadata must not replace the first occurrence'
    repeats = [replacement, target, _post(excluded_id), _post(locked_id)]
    app = _app([*first_posts, *repeats])
    if cross_page:
        app = _app(first_posts, next_posts=repeats)

    async with TestServer(app) as server:
        plan = (
            await _dry_run(tmp_path, server.make_url('/'), excluded_tags=('skip',))
        ).plan
        stats = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), excluded_tags=('skip',)
        )

    assert stats.posts_downloaded == plan.new_posts == 2 * int(not cached)
    assert stats.posts_cached == plan.unchanged_posts == 2 * int(cached)
    assert stats.posts_without_content == plan.excluded_posts == 1
    assert stats.posts_locked == 1
    assert stats.posts_failed == stats.posts_pending == plan.updated_posts == 0
    _assert_link(tmp_path, _local_link(tmp_path))
    store = JsonPostStore(tmp_path)
    saved_source = store.find_post(AUTHOR, SOURCE_ID)
    assert saved_source is not None
    assert saved_source.record is not None
    assert saved_source.record.post.title == source['title']
    assert store.find_post(AUTHOR, excluded_id) is None
    assert store.load_locked_post(AUTHOR, locked_id) is not None
    if source_before is not None:
        assert _state(_page(tmp_path, SOURCE_ID)) == source_before


@pytest.mark.parametrize('target_first', [False, True])
async def test_cached_source_picks_up_new_target_once(
    tmp_path: Path, *, target_first: bool
) -> None:
    source = _post(SOURCE_ID, link=TARGET_URL)
    async with TestServer(_app([source])) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    _assert_link(tmp_path, TARGET_URL)
    record_before = _state(_page(tmp_path, SOURCE_ID).with_name('post.json'))
    posts = [source, _post(TARGET_ID)]
    if target_first:
        posts.reverse()
    reporter = _QuietReporter()
    async with TestServer(_app(posts)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)
        _assert_link(tmp_path, _local_link(tmp_path))
        assert stats.posts_downloaded == 2
        assert stats.posts_cached == 0
        assert (
            _state(_page(tmp_path, SOURCE_ID).with_name('post.json')) == record_before
        )
        assert not any('SKIP (unchanged):' in message for message in reporter.notices)
        page_before = _state(_page(tmp_path, SOURCE_ID))
        repeated = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert repeated.posts_cached == 2
    assert repeated.posts_downloaded == 0
    assert _state(_page(tmp_path, SOURCE_ID)) == page_before


@pytest.mark.parametrize('target_first', [False, True])
async def test_restoring_target_page_does_not_rewrite_unchanged_source(
    tmp_path: Path, *, target_first: bool
) -> None:
    posts = [_post(SOURCE_ID, link=TARGET_URL), _post(TARGET_ID)]
    async with TestServer(_app(posts)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    source_before = _state(_page(tmp_path, SOURCE_ID))
    _page(tmp_path, TARGET_ID).unlink()
    if target_first:
        posts.reverse()
    async with TestServer(_app(posts)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert _page(tmp_path, TARGET_ID).is_file()
    assert _state(_page(tmp_path, SOURCE_ID)) == source_before
    assert stats.posts_cached == stats.posts_downloaded == 1


@pytest.mark.parametrize('target_first', [False, True])
@pytest.mark.parametrize('title', ['lesson', 'cafe\u0301'])
async def test_portable_future_folders_match_dry_run_in_either_order(
    tmp_path: Path, title: str, *, target_first: bool
) -> None:
    source = _post(SOURCE_ID, link=TARGET_URL)
    async with TestServer(_app([source])) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    target = _post(TARGET_ID)
    target['title'] = title
    other = _post('10000000-0000-4000-8000-000000000003')
    other['title'] = title.upper()
    target_dto = PostDTO.model_validate(target)
    name = compose_post_directory_name(
        title, target_dto.created_at, TARGET_ID, collision=int(not target_first)
    )
    expected_folder = f'{AUTHOR}/{name}'
    _save_source_for_future_target(tmp_path, expected_folder)
    source_before = _state(_page(tmp_path, SOURCE_ID))
    targets = [target, other] if target_first else [other, target]

    async with TestServer(_app([source, *targets])) as server:
        plan = (await _dry_run(tmp_path, server.make_url('/'))).plan
        assert plan.new_posts == 2
        assert plan.updated_posts == 0
        assert plan.unchanged_posts == 1
        assert _state(_page(tmp_path, SOURCE_ID)) == source_before
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())

    assert _page(tmp_path, TARGET_ID).parent.relative_to(tmp_path).as_posix() == (
        expected_folder
    )
    assert _state(_page(tmp_path, SOURCE_ID)) == source_before
    assert stats.posts_downloaded == 2
    assert stats.posts_cached == 1


def _save_source_for_future_target(root: Path, folder: str) -> None:
    source = JsonPostStore(root).find_post(AUTHOR, SOURCE_ID)
    assert source is not None
    assert source.record is not None
    page = prepare_post_page(
        source.record, folder=source.folder, link_resolver=_FutureTarget(folder)
    )
    _page(root, SOURCE_ID).write_bytes(page.content)


@pytest.mark.parametrize('target_state', ['locked', 'excluded', 'page-failed'])
async def test_unpublished_target_keeps_remote_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_state: str
) -> None:
    posts = [_post(SOURCE_ID, link=TARGET_URL), _post(TARGET_ID)]
    excluded_tags: tuple[str, ...] = ()
    if target_state == 'locked':
        posts[1]['hasAccess'] = False
    if target_state == 'excluded':
        posts[1]['tags'] = [{'title': 'skip'}]
        excluded_tags = ('skip',)
    if target_state == 'page-failed':
        original = post_pages_module.write_html_page

        def fail_target(
            path: Path, content: bytes, *, only_if_changed: bool = False
        ) -> bool:
            if path.parent.name.endswith(f'({TARGET_ID[:8]})'):
                message = 'Target page failed'
                raise OSError(message)
            return original(path, content, only_if_changed=only_if_changed)

        monkeypatch.setattr(post_pages_module, 'write_html_page', fail_target)
    async with TestServer(_app(posts)) as server:
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            excluded_tags=excluded_tags,
        )
    _assert_link(tmp_path, TARGET_URL)
    assert stats.posts_downloaded == 1


async def test_initial_record_failure_cannot_publish_unsaved_link_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_save(_state: PostDownloadState) -> None:
        message = 'Record cannot be saved'
        raise OSError(message)

    monkeypatch.setattr(PostDownloadState, 'save_initial', fail_save)
    async with TestServer(_app([_post(SOURCE_ID, link=TARGET_URL)])) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert stats.posts_failed == 1
    _assert_no_post_files(tmp_path)


def _assert_no_post_files(root: Path) -> None:
    assert not list(root.rglob('post.html'))
    assert not list(root.rglob('post.json'))


@pytest.mark.parametrize('cached_source', [False, True])
async def test_listing_error_does_not_repair_links(
    tmp_path: Path, *, cached_source: bool
) -> None:
    posts = [_post(SOURCE_ID, link=TARGET_URL), _post(TARGET_ID)]
    if cached_source:
        async with TestServer(_app(posts[:1])) as server:
            await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    async with TestServer(_app(posts, fail_next_page=True)) as server:
        with pytest.raises(BoostyAPIError):
            await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert _page(tmp_path, TARGET_ID).is_file()
    _assert_link(tmp_path, TARGET_URL)


@pytest.mark.parametrize('stop', ['cancelled', 'systemic'])
@pytest.mark.parametrize('cached_source', [False, True])
async def test_interrupted_run_does_not_repair_links(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop: str,
    *,
    cached_source: bool,
) -> None:
    posts = [_post(SOURCE_ID, link=TARGET_URL), _post(TARGET_ID)]
    if cached_source:
        async with TestServer(_app(posts[:1])) as server:
            await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    fail_ids = [f'90000000-0000-4000-8000-{n:012d}' for n in range(5)]
    posts.extend(_post(post_id) for post_id in fail_ids)
    execute = DownloadSinglePostUseCase.execute

    async def interrupt(self: DownloadSinglePostUseCase) -> None:
        if self.post_dto.id in fail_ids:
            if stop == 'cancelled':
                raise ApplicationCancelledError(self.post_dto.id)
            message = 'Disk stopped accepting writes'
            raise OSError(message)
        await execute(self)

    monkeypatch.setattr(DownloadSinglePostUseCase, 'execute', interrupt)
    expected = (
        ApplicationCancelledError
        if stop == 'cancelled'
        else ApplicationTooManyFailuresError
    )
    async with TestServer(_app(posts)) as server:
        with pytest.raises(expected):
            await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    _assert_link(tmp_path, TARGET_URL)


async def test_deferred_page_failure_is_reported_as_run_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _post(SOURCE_ID, link=TARGET_URL)
    async with TestServer(_app([source])) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    page_before = _state(_page(tmp_path, SOURCE_ID))
    original = post_pages_module.write_html_page

    def fail_source(
        path: Path, content: bytes, *, only_if_changed: bool = False
    ) -> bool:
        if path.parent.name.endswith(f'({SOURCE_ID[:8]})'):
            message = 'Source page cannot be updated'
            raise OSError(message)
        return original(path, content, only_if_changed=only_if_changed)

    monkeypatch.setattr(post_pages_module, 'write_html_page', fail_source)
    reporter = _QuietReporter()
    async with TestServer(_app([source, _post(TARGET_ID)])) as server:
        with pytest.raises(OSError, match='Source page cannot be updated'):
            await _run_download(tmp_path, server.make_url('/'), reporter)
    assert _page(tmp_path, TARGET_ID).is_file()
    assert _state(_page(tmp_path, SOURCE_ID)) == page_before
    assert not reporter.errors
    assert not reporter.warnings


@pytest.mark.parametrize('first_changes', [False, True])
async def test_late_repair_failure_keeps_completed_and_pending_results_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, first_changes: bool
) -> None:
    first_target = TARGET_URL
    if not first_changes:
        first_target = f'https://boosty.to/{AUTHOR}/posts/absent'
    first = _post(SOURCE_ID, link=first_target)
    second_id = '20000000-0000-4000-8000-000000000003'
    second = _post(second_id, link=TARGET_URL)
    async with TestServer(_app([first, second])) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    observed: list[RunStatistics] = []
    execute = DownloadAllPostUseCase.execute
    write_page = post_pages_module.write_html_page

    async def observe_run(use_case: DownloadAllPostUseCase) -> None:
        observed.append(use_case.context.run_statistics)
        await execute(use_case)

    def fail_second(
        path: Path, content: bytes, *, only_if_changed: bool = False
    ) -> bool:
        if path.parent.name.endswith(f'({second_id[:8]})'):
            message = 'Second deferred page failed'
            raise OSError(message)
        return write_page(path, content, only_if_changed=only_if_changed)

    monkeypatch.setattr(DownloadAllPostUseCase, 'execute', observe_run)
    monkeypatch.setattr(post_pages_module, 'write_html_page', fail_second)
    async with TestServer(_app([first, second, _post(TARGET_ID)])) as server:
        with pytest.raises(OSError, match='Second deferred page failed'):
            await _run_download(tmp_path, server.make_url('/'), _QuietReporter())

    assert len(observed) == 1
    stats = observed[0]
    assert stats.posts_downloaded == 1 + int(first_changes)
    assert stats.posts_cached == int(not first_changes)
    assert stats.posts_pending == 1
    assert stats.posts_failed == 0


async def test_single_cached_post_refreshes_links_without_changing_record(
    tmp_path: Path,
) -> None:
    source = _post(SOURCE_ID, link=TARGET_URL)
    async with TestServer(_app([source])) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    async with TestServer(_app([_post(TARGET_ID)])) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    record_before = _state(_page(tmp_path, SOURCE_ID).with_name('post.json'))
    async with TestServer(_app([source])) as server:
        stats = await _run_download(
            tmp_path, server.make_url('/'), _QuietReporter(), post_id=SOURCE_ID
        )
    _assert_link(tmp_path, _local_link(tmp_path))
    assert stats.posts_downloaded == 1
    assert stats.posts_cached == 0
    assert _state(_page(tmp_path, SOURCE_ID).with_name('post.json')) == record_before


async def test_retry_refresh_publishes_only_current_authored_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _post(SOURCE_ID, link=TARGET_URL)
    refreshed = _post(SOURCE_ID)
    for payload in (source, refreshed):
        payload['data'].append(file_chunk())
        payload['contentCounters']['file'] = 1
    served: list[str] = []
    writes: list[bytes] = []
    original = post_pages_module.write_html_page

    def capture_page(
        path: Path, content: bytes, *, only_if_changed: bool = False
    ) -> bool:
        writes.append(content)
        return original(path, content, only_if_changed=only_if_changed)

    monkeypatch.setattr(post_pages_module, 'write_html_page', capture_page)
    app = _build_app(
        served,
        payload=source,
        refreshed_payload=refreshed,
        fail_first_file=True,
        first_file_status=400,
    )
    async with TestServer(app) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    html = _page(tmp_path, SOURCE_ID).read_text(encoding='utf-8')
    assert 'Saved lesson' in html
    assert 'Related lesson' not in html
    assert TARGET_URL not in html
    assert len(writes) == 1
    assert stats.posts_downloaded == 1
    assert stats.posts_failed == 0
    assert stats.media.files == 1


@pytest.mark.parametrize('single_post', [False, True])
@pytest.mark.parametrize('render_fails', [False, True])
async def test_cli_summary_distinguishes_finished_and_failed_link_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    single_post: bool,
    render_fails: bool,
) -> None:
    initialize_library(tmp_path)
    source = _post(SOURCE_ID, link=TARGET_URL)
    for post in (source, _post(TARGET_ID)):
        async with TestServer(_app([post])) as server:
            await _run_download(tmp_path, server.make_url('/'), _QuietReporter())

    def fail_page(
        _path: Path, _content: bytes, *, only_if_changed: bool = False
    ) -> bool:
        del only_if_changed
        message = 'Cannot finalize local links'
        raise OSError(message)

    if render_fails:
        monkeypatch.setattr(post_pages_module, 'write_html_page', fail_page)
    output = io.StringIO()
    post_id = None
    if single_post:
        post_id = SOURCE_ID
    async with TestServer(_app([source])) as server:
        run = _run_cli_download(
            tmp_path, server.make_url('/'), output, monkeypatch, post_id=post_id
        )
        if render_fails:
            with pytest.raises(OSError, match='Cannot finalize local links'):
                await run
        else:
            await run

    text = ' '.join(output.getvalue().split())
    if render_fails:
        assert 'Run stopped after' in text
        assert 'Partial results' in text
        assert '1 pending page checks' in text
        assert 'unchanged' not in text
        assert 'Run finished' not in text
        assert 'Nothing new' not in text
    else:
        assert 'Run finished in' in text
        assert 'Posts: 1 downloaded' in text
        assert 'pending page checks' not in text
        assert 'Run stopped' not in text


async def _run_cli_download(
    root: Path,
    api_base: URL,
    output: io.StringIO,
    monkeypatch: pytest.MonkeyPatch,
    *,
    post_id: str | None,
) -> None:
    def settings(**_kwargs: object) -> AppSettings:
        return AppSettings(AUTHOR, root / AUTHOR, 'Bearer fixture', 'session=fixture')

    async def no_updates(_logger: object) -> None:
        pass

    @asynccontextmanager
    async def open_test_app(
        *_args: object, **_kwargs: object
    ) -> AsyncGenerator[App, None]:
        async with ClientSession() as session:
            http = RetryClient(session, retry_options=ExponentialRetry(attempts=1))
            yield App(
                api=BoostyAPIClient(http, base_url=api_base / 'v1/'),
                media_http=http,
                post_store=JsonPostStore(root),
                reporter=ConsoleProgressReporter(
                    console=Console(file=output, width=120),
                    logger=logging.getLogger(__name__),
                ),
            )

    monkeypatch.setattr(download_command, 'load_settings', settings)
    monkeypatch.setattr(download_command, 'open_app', open_test_app)
    monkeypatch.setattr(download_command, 'notify_about_updates', no_updates)
    await download_command._download_handler(  # pyright: ignore[reportPrivateUsage]
        username=AUTHOR,
        config_path=root / 'config.yaml',
        post_id=post_id,
        content_type_filter=[DownloadContentTypeFilter.post_content],
        preferred_video_quality=VideoQualityOption.medium,
        request_delay_seconds=0,
        library_root=root,
        cache_directory=None,
        skip_all_failures=False,
        dry_run=False,
    )
