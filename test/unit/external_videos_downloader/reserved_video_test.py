"""External video results belong to persisted reservations and stopped workers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Event, Thread, get_ident
from typing import TYPE_CHECKING, Any, cast

import pytest
from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import DownloadError, ExtractorError
from yt_dlp.YoutubeDL import YoutubeDL as RealYoutubeDL

from boosty_downloader.infrastructure.external_videos_downloader import (
    external_videos_downloader as module,
)
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideoDownloadStatus,
    ExternalVideosDownloader,
    ExtVideoDownloadError,
    ExtVideoInfoError,
    ExtVideoUnavailableError,
)
from boosty_downloader.infrastructure.media_transfer import MediaTarget

if TYPE_CHECKING:
    from collections.abc import Iterator

    from boosty_downloader.infrastructure.external_videos_downloader.prepared_video import (
        PreparedExternalVideo,
    )

URL = 'https://video.example/watch/one'
PAYLOAD = b'Completed external video'


@dataclass
class _Scenario:
    extension: str = 'mp4'
    final_extension: str = 'mp4'
    title: str = 'A video'
    probe_error: DownloadError | None = None
    download_error: DownloadError | None = None
    capture_output: bool = True
    events: list[str] = field(default_factory=list[str])
    outputs: list[Path] = field(default_factory=list[Path])


def _install_yt_dlp(monkeypatch: pytest.MonkeyPatch, scenario: _Scenario) -> None:
    class FakeYoutubeDL(RealYoutubeDL):
        def extract_info(
            self,
            url: str,
            download: bool = True,  # noqa: FBT001, FBT002 - yt-dlp API
            *args: object,
            **kwargs: object,
        ) -> Any:  # noqa: ANN401 - yt-dlp API
            del url, args, kwargs
            assert not download
            scenario.events.append('probe')
            if scenario.probe_error is not None:
                raise scenario.probe_error
            return {'id': 'one', 'title': scenario.title, 'ext': scenario.extension}

        def process_ie_result(
            self,
            ie_result: Any,  # noqa: ANN401 - yt-dlp API
            download: bool = True,  # noqa: FBT001, FBT002 - yt-dlp API
            extra_info: Any = None,  # noqa: ANN401 - yt-dlp API
        ) -> Any:  # noqa: ANN401 - yt-dlp API
            del extra_info
            assert download
            assert ie_result['id'] == 'one'
            scenario.events.append('transfer')
            if scenario.download_error is not None:
                raise scenario.download_error
            params = cast('dict[str, Any]', self.params)
            template = cast('str', params['outtmpl']['default'])
            source = Path(template % {'ext': scenario.final_extension})
            source.write_bytes(PAYLOAD)
            scenario.outputs.append(source)
            for hook in params['progress_hooks']:
                hook(
                    {
                        'filename': str(source),
                        'downloaded_bytes': len(PAYLOAD),
                        'total_bytes': len(PAYLOAD),
                    }
                )
            if not scenario.capture_output:
                return ie_result
            return cast('Any', self).post_process(
                str(source), {**ie_result, 'ext': scenario.final_extension}
            )

    monkeypatch.setattr(module, 'YoutubeDL', FakeYoutubeDL)


def _find_files(root: Path, pattern: str) -> list[Path]:
    return list(root.rglob(pattern))


def _reserve(
    root: Path, filename: str, *, media_id: str = 'external_video:one'
) -> MediaTarget:
    return MediaTarget(root, 'author/post', f'external_videos/{filename}', media_id)


async def test_reservation_precedes_transfer_and_after_move_supplies_actual_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _Scenario(final_extension='webm')
    _install_yt_dlp(monkeypatch, scenario)
    reservations: list[str] = []
    progress: list[ExternalVideoDownloadStatus] = []
    owner_thread = get_ident()

    def reserve(filename: str) -> MediaTarget:
        assert get_ident() == owner_thread
        reservations.append(filename)
        scenario.events.append('reserve')
        return _reserve(tmp_path, filename)

    result = await ExternalVideosDownloader().download_reserved_video(
        URL, reserve, progress.append
    )

    assert scenario.events == ['probe', 'reserve', 'transfer', 'reserve']
    assert reservations == ['A video.mp4', 'A video.webm']
    assert result.path == tmp_path / 'author/post/external_videos/A video.webm'
    assert result.path.read_bytes() == PAYLOAD
    assert result.size == len(PAYLOAD)
    assert progress[-1].delta_bytes == len(PAYLOAD)
    assert not scenario.outputs[0].parent.exists()


async def test_unchanged_extension_requires_one_reservation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_yt_dlp(monkeypatch, _Scenario())
    filenames: list[str] = []

    def reserve(filename: str) -> MediaTarget:
        filenames.append(filename)
        return _reserve(tmp_path, filename)

    await ExternalVideosDownloader().download_reserved_video(URL, reserve)

    assert filenames == ['A video.mp4']


@pytest.mark.parametrize('final_reservation', [False, True])
async def test_reservation_save_failure_never_publishes_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, final_reservation: bool
) -> None:
    scenario = _Scenario(final_extension='webm')
    _install_yt_dlp(monkeypatch, scenario)
    failure = OSError('Record save failed')
    reservations: list[str] = []

    def reserve(filename: str) -> MediaTarget:
        reservations.append(filename)
        if not final_reservation or len(reservations) == 2:
            raise failure
        return _reserve(tmp_path, filename)

    with pytest.raises(OSError, match='Record save failed') as caught:
        await ExternalVideosDownloader().download_reserved_video(URL, reserve)

    assert caught.value is failure
    assert not _find_files(tmp_path, '*.mp4')
    assert not _find_files(tmp_path, '*.webm')
    assert not _find_files(tmp_path, '.boosty-*.part')
    assert ('transfer' in scenario.events) is final_reservation


async def test_same_titles_keep_distinct_reserved_destinations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_yt_dlp(monkeypatch, _Scenario())
    downloader = ExternalVideosDownloader()
    first = await downloader.download_reserved_video(
        URL, lambda name: _reserve(tmp_path, name)
    )
    second = await downloader.download_reserved_video(
        URL + '/two',
        lambda _: _reserve(
            tmp_path, 'A video (two).mp4', media_id='external_video:two'
        ),
    )

    assert first.path != second.path
    assert first.path.read_bytes() == second.path.read_bytes() == PAYLOAD


async def test_occupied_final_file_survives_without_starting_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _Scenario()
    _install_yt_dlp(monkeypatch, scenario)
    destination = tmp_path / 'author/post/external_videos/A video.mp4'
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b'User file')

    with pytest.raises(FileExistsError):
        await ExternalVideosDownloader().download_reserved_video(
            URL, lambda name: _reserve(tmp_path, name)
        )

    assert scenario.events == ['probe']
    assert destination.read_bytes() == b'User file'


async def test_missing_after_move_result_is_not_guessed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = _Scenario(capture_output=False)
    _install_yt_dlp(monkeypatch, scenario)

    with pytest.raises(ExtVideoDownloadError):
        await ExternalVideosDownloader().download_reserved_video(
            URL, lambda name: _reserve(tmp_path, name)
        )

    assert not scenario.outputs[0].parent.exists()
    assert not _find_files(tmp_path, '*.mp4')


@pytest.mark.parametrize('during_transfer', [False, True])
@pytest.mark.parametrize('gone', [False, True])
async def test_probe_and_transfer_keep_gone_and_retryable_errors_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    during_transfer: bool,
    gone: bool,
) -> None:
    original = ExtractorError('Video failed', expected=gone)
    try:
        raise original
    except ExtractorError:
        assert original.__traceback__ is not None
        failure = DownloadError(
            'Video failed', (type(original), original, original.__traceback__)
        )
    scenario = _Scenario()
    if during_transfer:
        scenario.download_error = failure
    else:
        scenario.probe_error = failure
    _install_yt_dlp(monkeypatch, scenario)
    expected = (
        ExtVideoUnavailableError
        if gone
        else (ExtVideoDownloadError if during_transfer else ExtVideoInfoError)
    )

    with pytest.raises(expected):
        await ExternalVideosDownloader().download_reserved_video(
            URL, lambda name: _reserve(tmp_path, name)
        )

    assert not _find_files(tmp_path, '.boosty-*.part')


async def test_repeated_cancellation_waits_until_worker_stops_before_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_yt_dlp(monkeypatch, _Scenario())
    downloader = ExternalVideosDownloader()
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = Event()
    directories: list[Path] = []
    stopped = Event()

    def blocked_transfer(
        _prepared: PreparedExternalVideo,
        directory: Path,
        progress_hook: module.ExternalVideoDownloadProgressHook | None = None,
    ) -> Path:
        directories.append(directory)
        source = directory / 'fragment.part'
        source.write_bytes(b'Partial video')
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(timeout=5)
            assert progress_hook is not None
            progress_hook(ExternalVideoDownloadStatus('video', None, 1, None, 0, 1))
            pytest.fail('Cancellation must stop the worker')
        except KeyboardInterrupt as error:
            raise module.ExtVideoInterruptedByUserError(URL) from error
        finally:
            stopped.set()

    monkeypatch.setattr(downloader, 'download_prepared', blocked_transfer)
    task = asyncio.create_task(
        downloader.download_reserved_video(URL, lambda name: _reserve(tmp_path, name))
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        for _ in range(2):
            task.cancel()
            ready = loop.create_future()
            loop.call_soon(ready.set_result, None)
            await ready
            assert not task.done()
            assert directories[0].is_dir()
            assert not stopped.is_set()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)

    assert stopped.is_set()
    assert not directories[0].exists()
    assert not _find_files(tmp_path, '*.mp4')


@pytest.mark.parametrize('escape', ['absolute', 'parent'])
async def test_completed_output_cannot_escape_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, escape: str
) -> None:
    _install_yt_dlp(monkeypatch, _Scenario())
    downloader = ExternalVideosDownloader()
    outside = tmp_path / 'user-file.mp4'
    outside.write_bytes(b'Keep user data')

    def wrong_output(
        _prepared: PreparedExternalVideo,
        directory: Path,
        _hook: module.ExternalVideoDownloadProgressHook | None = None,
    ) -> Path:
        if escape == 'absolute':
            return outside
        destination = directory.parent / 'user-file.mp4'
        destination.write_bytes(b'Keep user data')
        return directory / '..' / 'user-file.mp4'

    monkeypatch.setattr(downloader, 'download_prepared', wrong_output)
    with pytest.raises(ValueError, match='escapes'):
        await downloader.download_reserved_video(
            URL, lambda name: _reserve(tmp_path, name)
        )
    assert outside.read_bytes() == b'Keep user data'
    assert not _find_files(tmp_path, '.boosty-*.part')


async def test_metadata_cancellation_waits_for_probe_without_creating_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloader = ExternalVideosDownloader()
    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    release = Event()
    stopped = Event()

    def probe(_url: str) -> PreparedExternalVideo:
        loop.call_soon_threadsafe(started.set)
        try:
            assert release.wait(timeout=5)
            raise ExtVideoInfoError(URL)
        finally:
            stopped.set()

    monkeypatch.setattr(downloader, 'prepare_video', probe)
    task = asyncio.create_task(
        downloader.download_reserved_video(URL, lambda name: _reserve(tmp_path, name))
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        ready = loop.create_future()
        loop.call_soon(ready.set_result, None)
        await ready
        assert not task.done()
        assert not (tmp_path / 'author').exists()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert stopped.is_set()
    assert not (tmp_path / 'author').exists()


@pytest.fixture
def direct_media_url() -> Iterator[str]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header('Content-Type', 'video/mp4')
            self.send_header('Content-Length', str(len(PAYLOAD)))
            self.end_headers()
            self.wfile.write(PAYLOAD)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - http.server API
            del format, args

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/video.mp4'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def test_installed_yt_dlp_processes_prepared_metadata_without_reextracting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, direct_media_url: str
) -> None:
    downloader = ExternalVideosDownloader()
    info = {
        'id': 'one',
        'title': 'Actual handoff',
        'ext': 'mp4',
        'url': direct_media_url,
        'protocol': 'http',
        'vcodec': 'h264',
        'acodec': 'aac',
        'height': 720,
    }

    def metadata(_url: str) -> dict[str, str | int]:
        return info

    monkeypatch.setattr(downloader, '_probe_video', metadata)

    def unexpected_extraction(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Prepared metadata must not extract the URL again')

    monkeypatch.setattr(RealYoutubeDL, 'extract_info', unexpected_extraction)
    result = await downloader.download_reserved_video(
        URL, lambda name: _reserve(tmp_path, name)
    )

    assert result.path.name == 'Actual handoff.mp4'
    assert result.path.read_bytes() == PAYLOAD
    assert result.size == len(PAYLOAD)


async def test_destination_created_during_transfer_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_yt_dlp(monkeypatch, _Scenario())
    downloader = ExternalVideosDownloader()
    transfer = downloader.download_prepared
    destination = tmp_path / 'author/post/external_videos/A video.mp4'

    def competing_transfer(
        prepared: PreparedExternalVideo,
        directory: Path,
        hook: module.ExternalVideoDownloadProgressHook | None = None,
    ) -> Path:
        source = transfer(prepared, directory, hook)
        destination.write_bytes(b'User file created during transfer')
        return source

    monkeypatch.setattr(downloader, 'download_prepared', competing_transfer)
    with pytest.raises(FileExistsError):
        await downloader.download_reserved_video(
            URL, lambda name: _reserve(tmp_path, name)
        )

    assert destination.read_bytes() == b'User file created during transfer'
    assert not _find_files(tmp_path, '.boosty-*.part')


async def test_linked_completed_output_never_publishes_the_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_yt_dlp(monkeypatch, _Scenario())
    downloader = ExternalVideosDownloader()
    outside = tmp_path / 'user-file.mp4'
    outside.write_bytes(b'Keep user data')

    def linked_output(
        _prepared: PreparedExternalVideo,
        directory: Path,
        _hook: module.ExternalVideoDownloadProgressHook | None = None,
    ) -> Path:
        source = directory / 'video.mp4'
        try:
            source.symlink_to(outside)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                pytest.skip('Creating symlinks requires Windows developer mode')
            raise
        return source

    monkeypatch.setattr(downloader, 'download_prepared', linked_output)
    with pytest.raises(ValueError, match='filesystem link'):
        await downloader.download_reserved_video(
            URL, lambda name: _reserve(tmp_path, name)
        )

    assert outside.read_bytes() == b'Keep user data'
    assert not _find_files(tmp_path, '.boosty-*.part')


@pytest.mark.parametrize('playlist_only', [False, True])
def test_metadata_selects_one_video_but_rejects_a_playlist_link(
    monkeypatch: pytest.MonkeyPatch, *, playlist_only: bool
) -> None:
    class PlaylistContextIE(InfoExtractor):
        _VALID_URL = r'https://video.example/(?P<id>watch|playlist)'

        def _real_extract(self, url: str) -> Any:  # noqa: ANN401 - yt-dlp extractor API
            video_id = 'one' if '/watch?' in url else None
            if cast('Any', self)._yes_playlist('collection', video_id):
                return self.playlist_result([], 'collection', 'Playlist')
            return {
                'id': 'one',
                'title': 'Selected video',
                'ext': 'mp4',
                'url': 'https://cdn.example/video.mp4',
                'vcodec': 'h264',
                'acodec': 'aac',
            }

    def isolated_downloader(params: Any = None) -> RealYoutubeDL:  # noqa: ANN401 - yt-dlp options
        downloader = RealYoutubeDL(params, auto_init=False)
        downloader.add_info_extractor(PlaylistContextIE())
        return downloader

    monkeypatch.setattr(module, 'YoutubeDL', isolated_downloader)
    downloader = ExternalVideosDownloader()
    if playlist_only:
        with pytest.raises(ExtVideoInfoError):
            downloader.prepare_video('https://video.example/playlist?list=collection')
    else:
        prepared = downloader.prepare_video(
            'https://video.example/watch?v=one&list=collection'
        )
        assert prepared.filename == 'Selected video.mp4'
