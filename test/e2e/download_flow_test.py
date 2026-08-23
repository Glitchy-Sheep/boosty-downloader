"""End-to-end: a full download run against a local Boosty-shaped server.

The server serves the sanitized fixture post and small media blobs. The run
uses the real API client, file downloader, cache and renderer - only the
console reporter and yt-dlp are absent. This is the safety net for the DI
and use-case refactoring stages: the on-disk tree must not change.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, cast

from aiohttp import ClientSession, web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient

from boosty_downloader.application.di.download_context import DownloadContext
from boosty_downloader.application.filtering import (
    BoostyOkVideoType,
    DownloadContentTypeFilter,
)
from boosty_downloader.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.infrastructure.loggers.base import RichLogger
from boosty_downloader.infrastructure.loggers.failed_downloads_logger import (
    FailedDownloadsLogger,
)
from boosty_downloader.infrastructure.post_caching.post_cache import (
    SQLitePostCache,
)

if TYPE_CHECKING:
    from yarl import URL

    from boosty_downloader.cli.console_progress_reporter import ProgressReporter
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )

FIXTURE_FILE = Path(__file__).parents[1] / 'fixtures' / 'single_post.json'
AUTHOR = 'example_author'
POST_DIR_NAME = '2025-06-15 - Fixture post with every content type (00000000)'

# The committed fixture points at these fake hosts; the server rewrites them
# to itself so every media request stays local.
_FAKE_HOSTS = ('https://cdn.example', 'https://images.example', 'https://video.example')


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

    def success(self, message: str) -> None:
        del message

    def notice(self, message: str) -> None:
        self.notices.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


def _build_app(served_media: list[str], media_delay: float = 0.0) -> web.Application:
    fixture_text = FIXTURE_FILE.read_text(encoding='utf-8')

    async def listing(request: web.Request) -> web.Response:
        local_text = fixture_text
        for host in _FAKE_HOSTS:
            local_text = local_text.replace(host, f'http://{request.host}')
        return web.json_response(
            {
                'data': [json.loads(local_text)],
                'extra': {'offset': '', 'isLast': True},
            }
        )

    async def blob(request: web.Request) -> web.Response:
        served_media.append(request.path)
        if media_delay:
            await asyncio.sleep(media_delay)
        if '/image/' in request.path:
            return web.Response(body=b'png bytes', content_type='image/png')
        if request.path.endswith('.mp4'):
            return web.Response(body=b'mp4 bytes', content_type='video/mp4')
        if '/audio/' in request.path:
            return web.Response(body=b'mp3 bytes', content_type='audio/mpeg')
        return web.Response(body=b'file bytes', content_type='application/octet-stream')

    app = web.Application()
    app.router.add_get(f'/v1/blog/{AUTHOR}/post/', listing)
    app.router.add_get('/{tail:.*}', blob)
    return app


async def _run_download(
    destination: Path, api_base: URL, reporter: _QuietReporter
) -> None:
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
                external_videos_downloader=cast('ExternalVideosDownloader', None),
                post_cache=cache,
                filters=list(DownloadContentTypeFilter),
                preferred_video_quality=BoostyOkVideoType.medium,
                progress_reporter=cast('ProgressReporter', reporter),
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
        await _run_download(tmp_path, server.make_url('/'), reporter)

        assert reporter.errors == []
        _assert_post_tree(tmp_path)
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
        await _run_download(tmp_path, server.make_url('/'), reporter)

        assert len(served_media) == media_after_first
        assert any('cached' in notice for notice in reporter.notices)
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
