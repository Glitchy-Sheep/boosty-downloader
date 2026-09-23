"""End-to-end: a full download run against a local Boosty-shaped server.

The server serves the synthetic post and small media blobs. The run
uses the real API client, file downloader, cache and renderer - only the
console reporter and yt-dlp are absent. This is the safety net for the DI
and use-case refactoring stages: the on-disk tree must not change.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import TYPE_CHECKING, cast

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient
from support.synthetic_post import (
    AUDIO_SIZE,
    FAKE_HOSTS,
    FILE_SIZE,
    IMAGE_SIZE,
    synthetic_post,
)

from boosty_downloader.application import post_retry as post_retry_module
from boosty_downloader.application.blog_overview import MediaCounts
from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.filtering import (
    BoostyOkVideoType,
)
from boosty_downloader.application.run_statistics import RunStatistics
from boosty_downloader.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.application.use_cases.plan_download import (
    DryRunReport,
    PlanDownloadUseCase,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExtVideoUnavailableError,
)
from boosty_downloader.infrastructure.loggers.base import RichLogger
from boosty_downloader.infrastructure.loggers.failed_downloads_logger import (
    FailedDownloadsLogger,
)
from boosty_downloader.infrastructure.post_caching.post_cache import (
    SQLitePostCache,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from yarl import URL

    from boosty_downloader.application.run_statistics import RunStatistics
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )

AUTHOR = 'example_author'
POST_DIR_NAME = '2025-06-15 - Fixture post with every content type (00000000)'


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


def _blob_body(path: str) -> web.Response:
    """A few bytes of the right media type for every fixture link."""
    if '/image/' in path:
        return web.Response(body=b'png bytes', content_type='image/png')
    if path.endswith('.mp4'):
        return web.Response(body=b'mp4 bytes', content_type='video/mp4')
    if '/audio/' in path:
        return web.Response(body=b'mp3 bytes', content_type='audio/mpeg')
    return web.Response(body=b'file bytes', content_type='application/octet-stream')


def _build_app(
    served_media: list[str],
    media_delay: float = 0.0,
    *,
    fail_first_file: bool = False,
    dead_images: bool = False,
    external_video_url: str | None = None,
) -> web.Application:
    fixture_text = json.dumps(synthetic_post())
    file_failures_left = 1 if fail_first_file else 0

    async def listing(request: web.Request) -> web.Response:
        # The synthetic post links to fake hosts; the server rewrites them
        # to itself so every media request stays local.
        local_text = fixture_text
        for host in FAKE_HOSTS:
            local_text = local_text.replace(host, f'http://{request.host}')
        post = json.loads(local_text)
        if external_video_url is not None:
            post['data'].append({'type': 'video', 'url': external_video_url})
        return web.json_response(
            {
                'data': [post],
                'extra': {'offset': '', 'isLast': True},
            }
        )

    async def blob(request: web.Request) -> web.Response:
        nonlocal file_failures_left
        served_media.append(request.path)
        if media_delay:
            await asyncio.sleep(media_delay)
        if '/file/' in request.path and file_failures_left:
            file_failures_left -= 1
            return web.Response(status=404)
        if '/image/' in request.path and dead_images:
            return web.Response(status=404)
        return _blob_body(request.path)

    app = web.Application()
    app.router.add_get(f'/v1/blog/{AUTHOR}/post/', listing)
    app.router.add_get('/{tail:.*}', blob)
    return app


class _GoneExternalVideos:
    """yt-dlp stand-in: every external video is deleted."""

    def download_video(self, **kwargs: object) -> Path:
        raise ExtVideoUnavailableError(str(kwargs['url']), 'This video is unavailable')


async def _run_download(
    destination: Path,
    api_base: URL,
    reporter: _QuietReporter,
    external_videos: ExternalVideosDownloader | None = None,
) -> RunStatistics:
    """One full download run wired exactly like the app, minus the console."""
    async with ClientSession() as session:
        retry_client = RetryClient(
            session, retry_options=ExponentialRetry(attempts=2, start_timeout=0.1)
        )
        boosty_api = BoostyAPIClient(retry_client, base_url=api_base / 'v1/')
        with SQLitePostCache(destination, RichLogger('e2e-cache')) as cache:
            context = DownloadContext(
                author_name=AUTHOR,
                downloader_session=retry_client,
                # The fixture has no external videos: yt-dlp must stay out.
                external_videos_downloader=cast(
                    'ExternalVideosDownloader', external_videos
                ),
                post_cache=cache,
                filters=list(DownloadContentTypeFilter),
                preferred_video_quality=BoostyOkVideoType.medium,
                progress_reporter=reporter,
                failed_logger=FailedDownloadsLogger(
                    destination / 'failed_downloads.log'
                ),
            )
            await DownloadAllPostUseCase(
                author_name=AUTHOR,
                boosty_api=boosty_api,
                destination=destination,
                download_context=context,
            ).execute()
            return context.run_statistics


def _assert_post_tree(destination: Path) -> None:
    """The on-disk layout is the app's public contract with its users."""
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
    assert 'boosty_videos/Fixture video (10000000).mp4' in html
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
        html = (tmp_path / POST_DIR_NAME / 'post.html').read_text(encoding='utf-8')
        assert 'href="files/fixture-archive.zip"' in html
        # The card names the file and shows the size the API reported.
        assert 'fixture-archive.zip' in html
        assert 'File · ZIP · 4.0 MB' in html
        # The closing statistics must describe exactly what landed on disk.
        assert stats.posts_downloaded == 1
        assert stats.media == MediaCounts(images=1, files=1, boosty_videos=1, audio=1)
        assert stats.downloaded_bytes == len(
            b'png bytes' + b'mp4 bytes' + b'file bytes' + b'mp3 bytes'
        )
    finally:
        await server.close()


async def test_second_run_serves_from_cache(tmp_path: Path) -> None:
    """A rerun must not touch the network for media: that is the cache promise."""
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
        assert any('cached' in notice for notice in reporter.notices)
        assert stats.posts_cached == 1
        assert stats.posts_downloaded == 0
        assert stats.media == MediaCounts()
    finally:
        await server.close()


async def test_media_of_one_post_downloads_in_parallel(tmp_path: Path) -> None:
    """Four media on a 0.4s-slow server must overlap: the sequential flow
    needed at least 1.6s, the parallel one fits well under that."""
    served_media: list[str] = []
    server = TestServer(_build_app(served_media, media_delay=0.4))
    await server.start_server()
    try:
        reporter = _QuietReporter()
        started = time.monotonic()
        await _run_download(tmp_path, server.make_url('/'), reporter)
        duration = time.monotonic() - started

        assert reporter.errors == []
        media_requests = [p for p in served_media if p != '/']
        assert len(media_requests) >= 4, 'the fixture post carries 4 media'
        assert duration < 1.3, (
            f'4 media x 0.4s must overlap, not queue (took {duration:.2f}s)'
        )

        html = (tmp_path / POST_DIR_NAME / 'post.html').read_text(encoding='utf-8')
        image_at = html.index('images/')
        video_at = html.index('boosty_videos/')
        audio_at = html.index('audio/')
        assert image_at < video_at < audio_at, (
            'the page must keep the author chunk order despite parallel finishes'
        )
    finally:
        await server.close()


async def _dry_run(destination: Path, api_base: URL) -> DryRunReport:
    """The dry-run wired exactly like the CLI does it."""
    async with ClientSession() as session:
        retry_client = RetryClient(
            session, retry_options=ExponentialRetry(attempts=2, start_timeout=0.1)
        )
        boosty_api = BoostyAPIClient(retry_client, base_url=api_base / 'v1/')
        with SQLitePostCache(destination, RichLogger('e2e-dry')) as cache:
            return await PlanDownloadUseCase(
                author_name=AUTHOR,
                boosty_api=boosty_api,
                logger=RichLogger('e2e-dry'),
                post_cache=cache,
                filters=list(DownloadContentTypeFilter),
                preferred_video_quality=BoostyOkVideoType.medium,
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

        # After a real run the same plan collapses to "everything complete".
        await _run_download(tmp_path, server.make_url('/'), _QuietReporter())
        media_downloaded = len(served_media)
        assert media_downloaded > 0

        report = await _dry_run(tmp_path, server.make_url('/'))

        assert report.plan.complete_posts == 1
        assert report.plan.new_posts == 0
        assert report.plan.media == MediaCounts()
        assert len(served_media) == media_downloaded, 'second dry-run fetched media'
    finally:
        await server.close()


async def test_a_post_with_a_dead_image_still_gets_a_readable_page(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A piece that never downloads must not hide the whole post: the page is
    written with a note at its place, the other content types are cached, and
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
        post_dir = tmp_path / POST_DIR_NAME
        html = (post_dir / 'post.html').read_text(encoding='utf-8')
        assert 'Image not downloaded' in html
        assert 'Unexpected status code: 404' in html
        assert '<img' not in html
        assert 'boosty_videos/Fixture video (10000000).mp4' in html
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
        html = (tmp_path / POST_DIR_NAME / 'post.html').read_text(encoding='utf-8')
        assert f'Video not downloaded: {gone_url}' in html
        assert 'This video is unavailable' in html
        assert f'href="{gone_url}">Open the original</a>' in html
        log = (tmp_path / 'failed_downloads.log').read_text(encoding='utf-8')
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
        html = (tmp_path / POST_DIR_NAME / 'post.html').read_text(encoding='utf-8')
        # The page was written on the first attempt without the file and
        # rewritten with its card when the retry brought it.
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
