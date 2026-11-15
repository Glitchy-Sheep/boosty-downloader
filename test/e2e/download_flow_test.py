"""End-to-end: a full download run against a local Boosty-shaped server.

The server serves the synthetic post and small media blobs. The run
uses the real API client, record store, file downloader and renderer.
Only the console reporter and yt-dlp are replaced.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

import pytest
from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient
from aiolimiter import AsyncLimiter
from support.raster_images import png_bytes
from support.synthetic_blog import BLOG_TITLE, OWNER_NAME, POST_COUNT, synthetic_blog
from support.synthetic_post import (
    AUDIO_SIZE,
    FAKE_HOSTS,
    FILE_ID,
    FILE_SIZE,
    IMAGE_SIZE,
    POST_ID,
    VIDEO_ID,
    file_chunk,
    synthetic_post,
)

from boosty_downloader.application import post_pages as post_pages_module
from boosty_downloader.application import post_retry as post_retry_module
from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.filtering import (
    BoostyOkVideoType,
)
from boosty_downloader.application.post_download_state import PostDownloadState
from boosty_downloader.application.post_preparation import PostPreparer
from boosty_downloader.application.run_statistics import RunStatistics
from boosty_downloader.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.application.use_cases.download_post_by_id import (
    DownloadPostByIdUseCase,
)
from boosty_downloader.application.use_cases.plan_download import (
    DryRunReport,
    PlanDownloadUseCase,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
    ExtVideoUnavailableError,
)
from boosty_downloader.infrastructure.library.author_records import read_locked_posts
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.loggers.base import RichLogger
from boosty_downloader.infrastructure.loggers.failed_downloads_logger import (
    FailedDownloadsLogger,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path
    from typing import Any

    from yarl import URL

    from boosty_downloader.application.run_statistics import RunStatistics
    from boosty_downloader.infrastructure.media_publication import PublishedFile

AUTHOR = 'example_author'
POST_DIR_NAME = '2025-06-15 - Fixture post with every content type (00000000)'
THUMBNAIL_PNG = png_bytes()


class _QuietReporter:
    """Collects messages instead of rendering rich console output."""

    def __init__(self) -> None:
        self.notices: list[str] = []
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def create_task(self, *args: object, **kwargs: object) -> uuid.UUID:
        del args, kwargs
        return uuid.uuid4()

    def update_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def complete_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def info(self, message: str) -> None:
        del message

    def success(self, message: str) -> None:
        del message

    def notice(self, message: str) -> None:
        self.notices.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


class _MediaOverlap:
    """Keep responses pending until every distinct post media request has arrived."""

    def __init__(self, *, expected: int) -> None:
        self.expected = expected
        self.pending: set[str] = set()
        self.all_started = asyncio.Event()
        self.release = asyncio.Event()

    async def hold(self, path: str) -> None:
        self.pending.add(path)
        if len(self.pending) == self.expected:
            self.all_started.set()
        try:
            await self.release.wait()
        finally:
            self.pending.remove(path)


def _blob_body(path: str) -> web.Response:
    """A few bytes of the right media type for every fixture link."""
    if any(part in path for part in ('/image/', '/preview/', '/teaser/')):
        return web.Response(body=b'png bytes', content_type='image/png')
    if path.endswith('.mp4'):
        return web.Response(body=b'mp4 bytes', content_type='video/mp4')
    if '/audio/' in path:
        return web.Response(body=b'mp3 bytes', content_type='audio/mpeg')
    return web.Response(body=b'file bytes', content_type='application/octet-stream')


async def _author_asset(request: web.Request) -> web.Response:
    return _blob_body(request.path)


def _local_payload(text: str, host: str) -> dict[str, Any]:
    for source_host in FAKE_HOSTS:
        text = text.replace(source_host, f'http://{host}')
    return json.loads(text)


@dataclass
class _OptionalImageRequests:
    thumbnails: list[str]
    auxiliary: list[str]
    thumbnail_status: int

    @web.middleware
    async def handle(
        self,
        request: web.Request,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
    ) -> web.StreamResponse:
        if request.query.get('mw') == '480':
            self.thumbnails.append(request.raw_path)
            return web.Response(
                status=self.thumbnail_status,
                body=THUMBNAIL_PNG,
                content_type='image/png',
            )
        if request.path.startswith(('/preview/', '/teaser/')):
            self.auxiliary.append(request.path)
        return await handler(request)


def _build_app(  # noqa: PLR0913 - independent fake-server failure modes
    served_media: list[str],
    *,
    media_overlap: _MediaOverlap | None = None,
    fail_first_file: bool = False,
    dead_images: bool = False,
    external_video_url: str | None = None,
    blog_failures: list[int] | None = None,
    payload: dict[str, Any] | None = None,
    refreshed_payload: dict[str, Any] | None = None,
    first_file_status: int = 404,
    served_thumbnails: list[str] | None = None,
    served_auxiliary: list[str] | None = None,
    thumbnail_status: int = 200,
) -> web.Application:
    """Collect primary transfers separately from optional thumbnail and preview traffic."""
    fixture_text = json.dumps(payload if payload is not None else synthetic_post())
    thumbnails = [] if served_thumbnails is None else served_thumbnails
    auxiliary = [] if served_auxiliary is None else served_auxiliary

    file_failures_left = 1 if fail_first_file else 0

    async def listing(request: web.Request) -> web.Response:
        # The synthetic post links to fake hosts; the server rewrites them
        # to itself so every media request stays local.
        post = _local_payload(fixture_text, request.host)
        if external_video_url is not None:
            post['data'].append({'type': 'video', 'url': external_video_url})
        return web.json_response(
            {
                'data': [post],
                'extra': {'offset': '', 'isLast': True},
            }
        )

    async def blog_info(request: web.Request) -> web.Response:
        if blog_failures:
            return web.Response(status=blog_failures.pop(0))
        return web.json_response(
            _local_payload(json.dumps(synthetic_blog()), request.host)
        )

    async def blob(request: web.Request) -> web.Response:
        nonlocal file_failures_left
        served_media.append(request.path)
        if media_overlap is not None:
            await media_overlap.hold(request.path)
        if '/file/' in request.path and file_failures_left:
            file_failures_left -= 1
            return web.Response(status=first_file_status)
        if '/image/' in request.path and dead_images:
            return web.Response(status=404)
        return _blob_body(request.path)

    async def single_post(request: web.Request) -> web.Response:
        fresh = (
            json.dumps(refreshed_payload)
            if refreshed_payload is not None
            else fixture_text
        )
        return web.json_response(_local_payload(fresh, request.host))

    optional_images = _OptionalImageRequests(thumbnails, auxiliary, thumbnail_status)
    app = web.Application(middlewares=[optional_images.handle])
    app.router.add_get(f'/v1/blog/{AUTHOR}', blog_info)
    app.router.add_get(f'/v1/blog/{AUTHOR}/post/', listing)
    app.router.add_get(f'/v1/blog/{AUTHOR}/post/{POST_ID}', single_post)
    app.router.add_get('/blog/{tail:.*}', _author_asset)
    app.router.add_get('/preview/{tail:.*}', _author_asset)
    app.router.add_get('/teaser/{tail:.*}', _author_asset)
    app.router.add_get('/{tail:.*}', blob)
    return app


class _GoneExternalVideos:
    """yt-dlp stand-in: every external video is deleted."""

    def __init__(self) -> None:
        self.calls = 0

    async def download_reserved_video(
        self, url: str, *args: object, **kwargs: object
    ) -> Path:
        del args, kwargs
        self.calls += 1
        raise ExtVideoUnavailableError(url, 'This video is unavailable')


async def _run_download(  # noqa: PLR0913 - isolated download scenarios
    destination: Path,
    api_base: URL,
    reporter: _QuietReporter,
    *,
    external_videos: ExternalVideosDownloader | None = None,
    excluded_tags: tuple[str, ...] = (),
    filters: list[DownloadContentTypeFilter] | None = None,
    post_id: str | None = None,
    restore_missing: bool = False,
) -> RunStatistics:
    """One full download run wired exactly like the app, minus the console."""
    async with ClientSession() as session:
        retry_client = RetryClient(
            session, retry_options=ExponentialRetry(attempts=2, start_timeout=0.1)
        )
        boosty_api = BoostyAPIClient(retry_client, base_url=api_base / 'v1/')
        context = DownloadContext(
            author_name=AUTHOR,
            downloader_session=retry_client,
            # The fixture has no external videos: yt-dlp must stay out.
            external_videos_downloader=cast(
                'ExternalVideosDownloader', external_videos
            ),
            post_store=JsonPostStore(destination),
            library_root=destination,
            filters=list(DownloadContentTypeFilter) if filters is None else filters,
            excluded_tags=excluded_tags,
            restore_missing=restore_missing,
            thumbnail_requests=AsyncLimiter(1000, time_period=1),
            preferred_video_quality=BoostyOkVideoType.medium,
            progress_reporter=reporter,
            failed_logger=FailedDownloadsLogger(
                destination / AUTHOR / 'failed_downloads.log'
            ),
        )
        if post_id is None:
            await DownloadAllPostUseCase(
                author_name=AUTHOR,
                boosty_api=boosty_api,
                destination=destination / AUTHOR,
                download_context=context,
            ).execute()
        else:
            await DownloadPostByIdUseCase(
                post_id=post_id,
                boosty_api=boosty_api,
                destination=destination / AUTHOR,
                download_context=context,
            ).execute()
        return context.run_statistics


def _assert_post_tree(destination: Path) -> None:
    """The on-disk layout is the app's public contract with its users."""
    destination = destination / AUTHOR
    post_dir = destination / POST_DIR_NAME
    tree = sorted(p.name for p in destination.iterdir())
    assert post_dir.is_dir(), f'actual tree: {tree}'

    images = sorted(p.name for p in (post_dir / 'images').iterdir())
    assert images == ['10000000-0000-4000-8000-000000000201.png']
    assert (post_dir / 'files' / 'fixture-archive.zip').read_bytes() == b'file bytes'
    videos = sorted(p.name for p in (post_dir / 'boosty_videos').iterdir())
    assert videos == ['Fixture video (10000000).mp4']
    audio = sorted(p.name for p in (post_dir / 'audio').iterdir())
    assert audio == ['fixture-song.mp3']

    html = (post_dir / 'post.html').read_text(encoding='utf-8')
    assert '<title>Fixture post with every content type</title>' in html
    assert 'images/10000000-0000-4000-8000-000000000201.png' in html
    assert 'boosty_videos/Fixture%20video%20%2810000000%29.mp4' in html
    assert 'audio/fixture-song.mp3' in html


async def test_full_run_builds_the_expected_post_tree(tmp_path: Path) -> None:
    served_media: list[str] = []
    server = TestServer(_build_app(served_media))
    await server.start_server()
    try:
        reporter = _QuietReporter()
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)

        assert reporter.errors == []
        _assert_post_tree(tmp_path)
        html = (tmp_path / AUTHOR / POST_DIR_NAME / 'post.html').read_text(
            encoding='utf-8'
        )
        assert 'href="files/fixture-archive.zip"' in html
        # The card names the file and shows its actual saved size.
        assert 'fixture-archive.zip' in html
        assert 'File · ZIP · 10 B' in html
        # The closing statistics must describe exactly what landed on disk.
        assert stats.posts_downloaded == 1
        assert stats.media == MediaCounts(images=1, files=1, boosty_videos=1, audio=1)
        assert stats.downloaded_bytes == len(
            b'png bytes' + b'mp4 bytes' + b'file bytes' + b'mp3 bytes'
        )
    finally:
        await server.close()


async def test_second_run_reuses_saved_media(tmp_path: Path) -> None:
    """A rerun must not touch the network for media: saved pieces are complete."""
    served_media: list[str] = []
    server = TestServer(_build_app(served_media))
    await server.start_server()
    try:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        media_after_first = len(served_media)
        assert media_after_first > 0

        reporter = _QuietReporter()
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)

        assert len(served_media) == media_after_first
        assert any('unchanged' in notice for notice in reporter.notices)
        assert stats.posts_cached == 1
        assert stats.posts_downloaded == 0
        assert stats.media == MediaCounts()
    finally:
        await server.close()


async def test_media_of_one_post_downloads_in_parallel(tmp_path: Path) -> None:
    """All four post media requests arrive before any media response is released."""
    served_media: list[str] = []
    overlap = _MediaOverlap(expected=4)
    reporter = _QuietReporter()
    async with TestServer(_build_app(served_media, media_overlap=overlap)) as server:
        download = asyncio.create_task(
            _run_download(tmp_path, server.make_url('/'), reporter)
        )
        try:
            # This timeout detects a stuck barrier; elapsed time is not the assertion.
            await asyncio.wait_for(overlap.all_started.wait(), timeout=10)
            assert len(overlap.pending) == overlap.expected
        finally:
            overlap.release.set()
            await asyncio.wait_for(download, timeout=10)
        assert reporter.errors == []

    html = (tmp_path / AUTHOR / POST_DIR_NAME / 'post.html').read_text(encoding='utf-8')
    image_at = html.index('images/')
    video_at = html.index('boosty_videos/')
    audio_at = html.index('audio/')
    assert image_at < video_at < audio_at, (
        'the page must keep the author chunk order despite parallel finishes'
    )


async def _dry_run(
    destination: Path,
    api_base: URL,
    *,
    excluded_tags: tuple[str, ...] = (),
    restore_missing: bool = False,
    filters: list[DownloadContentTypeFilter] | None = None,
) -> DryRunReport:
    """The dry-run wired exactly like the CLI does it."""
    async with ClientSession() as session:
        retry_client = RetryClient(
            session, retry_options=ExponentialRetry(attempts=2, start_timeout=0.1)
        )
        boosty_api = BoostyAPIClient(retry_client, base_url=api_base / 'v1/')
        return await PlanDownloadUseCase(
            author_name=AUTHOR,
            boosty_api=boosty_api,
            logger=RichLogger('e2e-dry'),
            preparer=PostPreparer(
                destination,
                JsonPostStore(destination),
                AUTHOR,
                BoostyOkVideoType.medium,
                restore_missing=restore_missing,
            ),
            filters=list(DownloadContentTypeFilter) if filters is None else filters,
            excluded_tags=excluded_tags,
        ).execute()


async def test_dry_run_promises_the_post_but_touches_no_media(tmp_path: Path) -> None:
    """The --dry-run contract: an honest plan and zero media requests."""
    served_media: list[str] = []
    server = TestServer(_build_app(served_media))
    await server.start_server()
    try:
        report = await _dry_run(tmp_path, server.make_url('/'))

        assert served_media == [], 'the dry-run must not touch a single media url'
        assert report.plan.new_posts == 1
        assert report.plan.media == MediaCounts(
            images=1, files=1, boosty_videos=1, audio=1
        )
        # Image, file and audio sizes straight from the synthetic post.
        assert report.plan.known_bytes == IMAGE_SIZE + FILE_SIZE + AUDIO_SIZE
        assert report.plan.unknown_size_videos == 1
        assert report.overview.total_posts == 1

        # After a real run the same plan reports an unchanged record.
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        media_downloaded = len(served_media)
        assert media_downloaded > 0

        report = await _dry_run(tmp_path, server.make_url('/'))

        assert report.plan.unchanged_posts == 1
        assert report.plan.new_posts == 0
        assert report.plan.media == MediaCounts()
        assert len(served_media) == media_downloaded, 'second dry-run fetched media'
    finally:
        await server.close()


async def test_a_post_with_a_dead_image_still_gets_a_readable_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A piece that never downloads must not hide the whole post: the page is
    written with a note at its place, the other media are saved, and
    the next run asks for the missing piece only and rewrites the page.
    """

    async def _no_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(post_retry_module.asyncio, 'sleep', _no_sleep)
    served_media: list[str] = []
    server = TestServer(_build_app(served_media, dead_images=True))
    await server.start_server()
    try:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())

        assert stats.posts_failed == 1
        post_dir = tmp_path / AUTHOR / POST_DIR_NAME
        html = (post_dir / 'post.html').read_text(encoding='utf-8')
        assert 'Image not downloaded' in html
        assert 'Unexpected status code: 404' in html
        assert '<img' not in html
        assert 'boosty_videos/Fixture%20video%20%2810000000%29.mp4' in html
        assert (post_dir / 'files' / 'fixture-archive.zip').exists()

        served_media.clear()
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())

        # 5 attempts, and every one of them asks for the image alone.
        assert len(served_media) == 5, served_media
        assert all('/image/' in path for path in served_media)
        assert 'Image not downloaded' in (post_dir / 'post.html').read_text(
            encoding='utf-8'
        )
    finally:
        await server.close()


async def test_a_gone_external_video_costs_one_attempt_and_keeps_the_post_readable(
    tmp_path: Path,
) -> None:
    """Issue #76 end to end: no retries on a deleted video, the rest of the post
    lands and the page marks the video's place with the site's reason.
    """
    gone_url = 'https://www.youtube.com/watch?v=gone'
    served_media: list[str] = []
    server = TestServer(_build_app(served_media, external_video_url=gone_url))
    await server.start_server()
    try:
        reporter = _QuietReporter()
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            reporter,
            external_videos=cast('ExternalVideosDownloader', _GoneExternalVideos()),
        )

        assert stats.posts_failed == 1
        assert not any('Attempt 1 failed' in w for w in reporter.warnings)
        assert any('retrying will not help' in e for e in reporter.errors)
        # One attempt: image, file, video, audio - and never again.
        assert len(served_media) == 4, served_media
        _assert_post_tree(tmp_path)
        html = (tmp_path / AUTHOR / POST_DIR_NAME / 'post.html').read_text(
            encoding='utf-8'
        )
        assert f'Video not downloaded: {gone_url}' in html
        assert 'This video is unavailable' in html
        assert f'href="{gone_url}">Open the original</a>' in html
        log = (tmp_path / AUTHOR / 'failed_downloads.log').read_text(encoding='utf-8')
        assert 'External video unavailable: This video is unavailable' in log
    finally:
        await server.close()


async def test_retried_post_fetches_only_the_failed_part_and_is_counted_once(
    tmp_path: Path,
) -> None:
    """A dead link must not cost the rest of the post: the retry fetches the failed
    file only, and the statistics describe each media piece once.
    """
    served_media: list[str] = []
    server = TestServer(_build_app(served_media, fail_first_file=True))
    await server.start_server()
    try:
        reporter = _QuietReporter()
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)

        assert any('Attempt 1 failed' in warning for warning in reporter.warnings)
        assert reporter.errors == []
        _assert_post_tree(tmp_path)
        html = (tmp_path / AUTHOR / POST_DIR_NAME / 'post.html').read_text(
            encoding='utf-8'
        )
        # The terminal page includes the file completed by the retry.
        assert 'href="files/fixture-archive.zip"' in html
        # First attempt: image, file (404), video, audio. Second attempt: the file.
        assert len(served_media) == 5, served_media
        assert '/file/' in served_media[-1], (
            'the retry must ask for the failed file only'
        )
        assert stats.posts_downloaded == 1
        assert stats.posts_failed == 0
        assert stats.media == MediaCounts(images=1, files=1, boosty_videos=1, audio=1)
        assert stats.downloaded_bytes == len(
            b'png bytes' + b'mp4 bytes' + b'file bytes' + b'mp3 bytes'
        )
    finally:
        await server.close()


@pytest.mark.parametrize('failures', [[], [503], [429]])
async def test_blog_info_uses_exact_route_and_existing_retries(
    failures: list[int],
) -> None:
    served_media: list[str] = []
    pending = failures.copy()
    async with (
        TestServer(_build_app(served_media, blog_failures=pending)) as server,
        RetryClient(
            retry_options=ExponentialRetry(
                attempts=2, start_timeout=0.01, statuses={429}
            )
        ) as session,
    ):
        client = BoostyAPIClient(session, base_url=server.make_url('/v1/'))
        blog = await client.get_blog_info(AUTHOR)

    assert blog.title == BLOG_TITLE
    assert blog.owner is not None
    assert blog.owner.name == OWNER_NAME
    assert blog.count is not None
    assert blog.count.posts == POST_COUNT
    assert blog.description is not None
    assert len(blog.description) == 5
    assert pending == []
    assert served_media == []


async def test_excluding_then_including_a_tag_preserves_download_eligibility(
    tmp_path: Path,
) -> None:
    served_media: list[str] = []
    async with TestServer(_build_app(served_media)) as server:
        report = await _dry_run(
            tmp_path, server.make_url('/'), excluded_tags=('FIXTURE',)
        )
        assert report.plan.excluded_posts == 1
        assert report.plan.new_posts == 0
        assert report.plan.media == MediaCounts()
        assert served_media == []

        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            excluded_tags=('FIXTURE',),
        )
        assert stats.posts_without_content == 1
        assert stats.posts_failed == 0
        assert served_media == []
        assert not (tmp_path / AUTHOR / POST_DIR_NAME).exists()

        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        assert served_media
        _assert_post_tree(tmp_path)

        served_media.clear()
        html_path = tmp_path / AUTHOR / POST_DIR_NAME / 'post.html'
        original_html = html_path.read_bytes()
        await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            excluded_tags=('fixture',),
        )
        assert served_media == []
        assert html_path.read_bytes() == original_html


async def test_separate_content_selections_build_one_complete_page(
    tmp_path: Path,
) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            filters=[DownloadContentTypeFilter.post_content],
        )
        assert len(served) == 1
        image = next((tmp_path / AUTHOR / POST_DIR_NAME / 'images').iterdir())
        original = (image.read_bytes(), image.stat().st_mtime_ns)
        plan = (await _dry_run(tmp_path, server.make_url('/'))).plan
        assert plan.updated_posts == 1
        assert plan.media == MediaCounts(files=1, audio=1, boosty_videos=1)
        served.clear()
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            filters=[
                DownloadContentTypeFilter.files,
                DownloadContentTypeFilter.boosty_videos,
                DownloadContentTypeFilter.audio,
            ],
        )
        assert len(served) == 3
        assert stats.media == plan.media
        assert (image.read_bytes(), image.stat().st_mtime_ns) == original
        _assert_post_tree(tmp_path)


async def test_retry_keeps_successful_peer_of_the_same_kind(tmp_path: Path) -> None:
    payload = synthetic_post()
    second = file_chunk()
    second.update(
        id='10000000-0000-4000-8000-000000000302',
        url='https://cdn.example/file/second',
        title='second.zip',
    )
    payload['data'].append(second)
    served: list[str] = []
    async with TestServer(
        _build_app(served, fail_first_file=True, payload=payload)
    ) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert served.count(f'/file/{FILE_ID}') == 2
    assert served.count('/file/second') == 1
    assert stats.media == MediaCounts(images=1, files=2, audio=1, boosty_videos=1)
    assert stats.posts_downloaded == 1
    assert stats.downloaded_bytes == len(
        b'png bytesmp4 bytesfile bytesfile bytesmp3 bytes'
    )


async def test_unavailable_video_does_not_block_retry_of_a_transient_file(
    tmp_path: Path,
) -> None:
    external = _GoneExternalVideos()
    served: list[str] = []
    app = _build_app(
        served, fail_first_file=True, external_video_url='https://video.example/gone'
    )
    async with TestServer(app) as server:
        reporter = _QuietReporter()
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            reporter,
            external_videos=cast('ExternalVideosDownloader', external),
        )
    assert external.calls == 1
    assert len(served) == 5
    assert stats.posts_failed == 1
    assert stats.media == MediaCounts(images=1, files=1, audio=1, boosty_videos=1)
    _assert_post_tree(tmp_path)
    assert any('retrying will not help' in message for message in reporter.errors)


async def test_page_is_rendered_once_after_all_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered: list[Path] = []
    original = post_pages_module.write_html_page

    def render(
        out_path: Path, content: bytes, *, only_if_changed: bool = False
    ) -> bool:
        rendered.append(out_path)
        return original(out_path, content, only_if_changed=only_if_changed)

    monkeypatch.setattr(post_pages_module, 'write_html_page', render)
    async with TestServer(_build_app([], fail_first_file=True)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert rendered == [tmp_path / AUTHOR / POST_DIR_NAME / 'post.html']


@pytest.mark.parametrize('dead_images', [False, True])
async def test_render_failure_preserves_completed_media_and_transfer_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dead_images: bool,
) -> None:
    original = post_pages_module.write_html_page

    def broken_render(
        out_path: Path, content: bytes, *, only_if_changed: bool = False
    ) -> bool:
        del out_path, content, only_if_changed
        message = 'page cannot be written'
        raise OSError(message)

    async def no_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(post_retry_module.asyncio, 'sleep', no_sleep)
    monkeypatch.setattr(post_pages_module, 'write_html_page', broken_render)
    served: list[str] = []
    async with TestServer(_build_app(served, dead_images=dead_images)) as server:
        reporter = _QuietReporter()
        stats = await _run_download(tmp_path, server.make_url('/'), reporter)
        assert stats.posts_failed == 1
        assert any('page cannot be written' in message for message in reporter.errors)
        if dead_images:
            assert any('404' in message for message in reporter.errors)
        located = JsonPostStore(tmp_path).find_post(AUTHOR, POST_ID)
        assert located is not None
        assert located.record is not None
        assert located.record.sync.page_template is None
        assert located.record.media[f'file:{FILE_ID}'].status is MediaStatus.downloaded
        served.clear()
        monkeypatch.setattr(post_pages_module, 'write_html_page', original)
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        assert all('/image/' in path for path in served)
        assert len(served) == (5 if dead_images else 0)
        assert (tmp_path / AUTHOR / POST_DIR_NAME / 'post.html').is_file()


async def test_published_video_is_recovered_after_completed_state_save_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = PostDownloadState.complete

    def fail_video_save(
        self: PostDownloadState, media_id: str, result: PublishedFile
    ) -> bool:
        if self.record.media[media_id].kind is MediaKind.boosty_video:
            message = 'record write interrupted'
            raise OSError(message)
        return original(self, media_id, result)

    monkeypatch.setattr(PostDownloadState, 'complete', fail_video_save)
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        assert stats.posts_failed == 1
        video = next((tmp_path / AUTHOR / POST_DIR_NAME / 'boosty_videos').iterdir())
        original_file = (video.read_bytes(), video.stat().st_mtime_ns)
        monkeypatch.setattr(PostDownloadState, 'complete', original)
        served.clear()
        report = await _dry_run(tmp_path, server.make_url('/'))
        assert report.plan.updated_posts == 1
        assert report.plan.media == MediaCounts()
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        assert stats.posts_downloaded == 1
        assert stats.media == MediaCounts()
        assert served == []
        assert (video.read_bytes(), video.stat().st_mtime_ns) == original_file
        _assert_post_tree(tmp_path)


async def test_refresh_losing_access_preserves_saved_body_and_previous_page(
    tmp_path: Path,
) -> None:
    locked = synthetic_post()
    locked.update(
        hasAccess=False,
        title='Locked response must not replace the saved body',
        data=[],
    )
    served: list[str] = []
    app = _build_app(
        served, fail_first_file=True, first_file_status=403, refreshed_payload=locked
    )
    async with TestServer(app) as server:
        await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            filters=[DownloadContentTypeFilter.post_content],
        )
        page = tmp_path / AUTHOR / POST_DIR_NAME / 'post.html'
        original_page = (page.read_bytes(), page.stat().st_mtime_ns)
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        assert stats.posts_failed == 1
        assert (page.read_bytes(), page.stat().st_mtime_ns) == original_page
        located = JsonPostStore(tmp_path).find_post(AUTHOR, POST_ID)
        assert located is not None
        assert located.record is not None
        assert located.record.post.title == 'Fixture post with every content type'
        assert located.record.blocks
        assert located.record.sync.page_template is None
        observations = read_locked_posts(tmp_path, AUTHOR)
        assert observations[POST_ID].post.title == locked['title']


async def test_author_rename_retains_post_folder(tmp_path: Path) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    payload = synthetic_post()
    payload['title'] = 'A new author title'
    served.clear()
    async with TestServer(_build_app(served, payload=payload)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert served == []
    assert stats.posts_downloaded == 1
    folders = [path.name for path in (tmp_path / AUTHOR).iterdir() if path.is_dir()]
    assert set(folders) == {POST_DIR_NAME, '.boosty-downloader'}
    html = (tmp_path / AUTHOR / POST_DIR_NAME / 'post.html').read_text(encoding='utf-8')
    assert '<title>A new author title</title>' in html


async def test_replaced_file_gets_free_name_and_preserves_removed_copy(
    tmp_path: Path,
) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    old_file = tmp_path / AUTHOR / POST_DIR_NAME / 'files' / 'fixture-archive.zip'
    old_bytes = (old_file.read_bytes(), old_file.stat().st_mtime_ns)
    payload = synthetic_post()
    replacement_id = '10000000-0000-4000-8000-000000000302'
    for chunk in payload['data']:
        if chunk.get('id') == FILE_ID:
            chunk.update(id=replacement_id, url='https://cdn.example/file/replacement')
    served.clear()
    async with TestServer(_build_app(served, payload=payload)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert served == ['/file/replacement']
    assert stats.media == MediaCounts(files=1)
    assert (old_file.read_bytes(), old_file.stat().st_mtime_ns) == old_bytes
    located = JsonPostStore(tmp_path).find_post(AUTHOR, POST_ID)
    assert located is not None
    assert located.record is not None
    old = located.record.media[f'file:{FILE_ID}']
    new = located.record.media[f'file:{replacement_id}']
    assert old.removed_at is not None
    assert new.removed_at is None
    assert new.path != old.path
    assert new.path is not None
    assert (tmp_path / located.folder / new.path).read_bytes() == b'file bytes'
    assert 'Removed by the author' in (old_file.parent.parent / 'post.html').read_text(
        encoding='utf-8'
    )


async def test_removed_file_returns_to_body_without_another_transfer(
    tmp_path: Path,
) -> None:
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    payload = synthetic_post()
    payload['data'] = [chunk for chunk in payload['data'] if chunk.get('id') != FILE_ID]
    served.clear()
    async with TestServer(_build_app(served, payload=payload)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    page = tmp_path / AUTHOR / POST_DIR_NAME / 'post.html'
    assert 'Removed by the author' in page.read_text(encoding='utf-8')
    assert served == []
    async with TestServer(_build_app(served)) as server:
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
    assert served == []
    assert 'Removed by the author' not in page.read_text(encoding='utf-8')
    assert 'href="files/fixture-archive.zip"' in page.read_text(encoding='utf-8')


async def test_real_external_adapter_saves_actual_bytes_in_post_record(
    tmp_path: Path,
) -> None:
    payload = synthetic_post()
    payload['data'].append({'type': 'video', 'url': 'https://cdn.example/external.mp4'})
    served: list[str] = []
    async with TestServer(_build_app(served, payload=payload)) as server:
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            external_videos=ExternalVideosDownloader(),
        )
        assert stats.posts_failed == 0
        assert stats.media.external_videos == 1
        located = JsonPostStore(tmp_path).find_post(AUTHOR, POST_ID)
        assert located is not None
        assert located.record is not None
        external = next(
            entry
            for entry in located.record.media.values()
            if entry.kind is MediaKind.external_video
        )
        assert external.status is MediaStatus.downloaded
        assert external.size == len(b'mp4 bytes')
        assert external.path is not None
        assert (tmp_path / located.folder / external.path).read_bytes() == b'mp4 bytes'
        served.clear()
        await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            external_videos=ExternalVideosDownloader(),
        )
        assert served == []


async def test_page_symlink_cannot_overwrite_a_file_outside_library(
    tmp_path: Path,
) -> None:
    library = tmp_path / 'library'
    async with TestServer(_build_app([])) as server:
        await _run_download(library, server.make_url('/'), _QuietReporter())
        outside = tmp_path / 'keep.txt'
        outside.write_bytes(b'keep outside bytes')
        page = library / AUTHOR / POST_DIR_NAME / 'post.html'
        page.unlink()
        try:
            page.symlink_to(outside)
        except OSError:
            pytest.skip('File symlink creation unavailable')
        reporter = _QuietReporter()
        stats = await _run_download(library, server.make_url('/'), reporter)
    assert outside.read_bytes() == b'keep outside bytes'
    assert page.is_symlink()
    assert stats.posts_failed == 1
    assert any('page destination is a link' in message for message in reporter.errors)


async def test_page_hardlink_is_replaced_without_modifying_other_name(
    tmp_path: Path,
) -> None:
    library = tmp_path / 'library'
    async with TestServer(_build_app([])) as server:
        await _run_download(library, server.make_url('/'), _QuietReporter())
        outside = tmp_path / 'keep.txt'
        outside.write_bytes(b'keep outside bytes')
        page = library / AUTHOR / POST_DIR_NAME / 'post.html'
        page.unlink()
        try:
            page.hardlink_to(outside)
        except OSError:
            pytest.skip('File hardlink creation unavailable')
    payload = synthetic_post()
    payload['title'] = 'Rebuild linked page'
    async with TestServer(_build_app([], payload=payload)) as server:
        stats = await _run_download(library, server.make_url('/'), _QuietReporter())
    assert stats.posts_downloaded == 1
    assert outside.read_bytes() == b'keep outside bytes'
    assert '<title>Rebuild linked page</title>' in page.read_text(encoding='utf-8')


async def test_refresh_checks_new_excluded_tags_before_saving_or_downloading(
    tmp_path: Path,
) -> None:
    excluded = synthetic_post()
    excluded.update(
        title='Excluded refreshed title', tags=[{'id': 99, 'title': 'skip-new-tag'}]
    )
    served: list[str] = []
    app = _build_app(
        served, fail_first_file=True, first_file_status=403, refreshed_payload=excluded
    )
    async with TestServer(app) as server:
        await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            filters=[DownloadContentTypeFilter.post_content],
        )
        page = tmp_path / AUTHOR / POST_DIR_NAME / 'post.html'
        original_page = (page.read_bytes(), page.stat().st_mtime_ns)
        served.clear()
        stats = await _run_download(
            tmp_path,
            server.make_url('/'),
            _QuietReporter(),
            excluded_tags=('skip-new-tag',),
        )
    assert served.count(f'/file/{FILE_ID}') == 1
    assert stats.posts_without_content == 1
    assert (page.read_bytes(), page.stat().st_mtime_ns) == original_page
    located = JsonPostStore(tmp_path).find_post(AUTHOR, POST_ID)
    assert located is not None
    assert located.record is not None
    assert located.record.post.title == 'Fixture post with every content type'


@pytest.mark.parametrize(
    ('media_id', 'relative_path', 'existing_bytes'),
    [
        (f'file:{FILE_ID}', 'files/fixture-archive.zip', b'wrong API size'),
        (f'boosty_video:{VIDEO_ID}', 'boosty_videos/Fixture video (10000000).mp4', b''),
    ],
)
async def test_recordless_folder_preserves_incomplete_preferred_and_unrelated_files(
    tmp_path: Path,
    media_id: str,
    relative_path: str,
    existing_bytes: bytes,
) -> None:
    folder = tmp_path / AUTHOR / POST_DIR_NAME
    existing = folder / relative_path
    existing.parent.mkdir(parents=True)
    existing.write_bytes(existing_bytes)
    unrelated = existing.parent / 'unrelated.keep'
    unrelated.write_bytes(b'foreign file')
    expected_mtime = existing.stat().st_mtime_ns
    unrelated_mtime = unrelated.stat().st_mtime_ns
    served: list[str] = []
    async with TestServer(_build_app(served)) as server:
        stats = await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        assert stats.posts_failed == 0
        assert existing.read_bytes() == existing_bytes
        assert existing.stat().st_mtime_ns == expected_mtime
        assert unrelated.read_bytes() == b'foreign file'
        assert unrelated.stat().st_mtime_ns == unrelated_mtime
        located = JsonPostStore(tmp_path).find_post(AUTHOR, POST_ID)
        assert located is not None
        assert located.record is not None
        entry = located.record.media[media_id]
        assert entry.status is MediaStatus.downloaded
        assert entry.path is not None
        assert entry.path != relative_path
        downloaded = tmp_path / located.folder / entry.path
        assert entry.size == downloaded.stat().st_size
        assert downloaded.read_bytes() in (b'file bytes', b'mp4 bytes')
        served.clear()
        assert (
            await _dry_run(tmp_path, server.make_url('/'))
        ).plan.media == MediaCounts()
        assert served == []
