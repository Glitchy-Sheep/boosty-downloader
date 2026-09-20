"""PostMediaDownloader: one folder per media kind, one progress and error shape.

The transport is faked at the module seam (`download_file`, the yt-dlp
wrapper); the layout, the naming policy and the error contract are real.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
)
from boosty_downloader.infrastructure import post_media_downloader as module
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideoDownloadStatus,
    ExtVideoDownloadError,
    ExtVideoError,
    ExtVideoInfoError,
    ExtVideoInterruptedByUserError,
    ExtVideoUnavailableError,
)
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadError,
    DownloadFileConfig,
    DownloadingStatus,
    DownloadIOFailureError,
    DownloadUnexpectedStatusError,
)
from boosty_downloader.infrastructure.post_media_downloader import (
    MediaDownloadError,
    MediaProgress,
    PostMediaDownloader,
)

if TYPE_CHECKING:
    from aiohttp_retry import RetryClient

    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )

RESOURCE = 'https://cdn.example/file'


def _downloader(post_dir: Path, external: object = None) -> PostMediaDownloader:
    return PostMediaDownloader(
        http=cast('RetryClient', None),
        external_videos=cast('ExternalVideosDownloader', external),
        post_dir=post_dir,
    )


def _noop(progress: MediaProgress) -> None:
    del progress


def _fake_transport(
    monkeypatch: pytest.MonkeyPatch, error: DownloadError | None = None
) -> list[DownloadFileConfig]:
    """Replace `download_file`: record the config, report one chunk, save or fail."""
    configs: list[DownloadFileConfig] = []

    async def fake_download_file(config: DownloadFileConfig) -> Path:
        configs.append(config)
        config.on_status_update(
            DownloadingStatus(
                name=config.filename,
                total_bytes=100,
                total_downloaded_bytes=40,
                downloaded_bytes=40,
            )
        )
        if error is not None:
            raise error
        # The fake saves the name as given: no extension guessing here.
        return config.destination / config.filename

    monkeypatch.setattr(module, 'download_file', fake_download_file)
    return configs


async def _download_every_kind(media: PostMediaDownloader) -> list[Path]:
    return [
        await media.download_image(
            PostDataChunkImage(url='https://cdn/image/40f9e868'), _noop
        ),
        await media.download_file(
            PostDataChunkFile(url='u', filename='any.appimage'), _noop
        ),
        await media.download_audio(
            PostDataChunkAudio(url='u', title='song.mp3'), _noop
        ),
        await media.download_boosty_video(
            PostDataChunkBoostyVideo(
                id='a2dd6942-7297', title='Update v1.2', url='u', quality='medium'
            ),
            _noop,
        ),
    ]


async def test_each_kind_lands_in_its_own_folder_relative_to_the_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The layout on disk and the relative paths in post.html are the user contract."""
    _fake_transport(monkeypatch)

    saved = await _download_every_kind(_downloader(tmp_path))

    assert saved == [
        Path('images/40f9e868'),
        Path('files/any.appimage'),
        Path('audio/song.mp3'),
        Path('boosty_videos/Update v1.2 (a2dd6942)'),
    ]
    assert all((tmp_path / path.parent).is_dir() for path in saved)


async def test_extension_policy_follows_the_name_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#75: author names (files, audio) are never touched; app-built names ask for one."""
    configs = _fake_transport(monkeypatch)

    await _download_every_kind(_downloader(tmp_path))

    assert {c.filename: c.guess_extension for c in configs} == {
        '40f9e868': True,
        'any.appimage': False,
        'song.mp3': False,
        'Update v1.2 (a2dd6942)': True,
    }


async def test_file_progress_comes_out_in_one_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_transport(monkeypatch)
    seen: list[MediaProgress] = []

    await _downloader(tmp_path).download_file(
        PostDataChunkFile(url='u', filename='a.zip'), seen.append
    )

    assert seen == [MediaProgress(downloaded_bytes=40, total_bytes=100, delta_bytes=40)]


@pytest.mark.parametrize(
    'error',
    [
        DownloadUnexpectedStatusError(
            status=404, response_message='Not Found', resource_url=RESOURCE
        ),
        DownloadIOFailureError(resource_url=RESOURCE, file=Path('a.zip')),
    ],
    ids=['status', 'io'],
)
async def test_transport_failure_becomes_a_media_error_with_the_cause_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: DownloadError
) -> None:
    """The expired-link check walks __cause__: the transport error must stay reachable."""
    if error.file is not None:
        error.file = tmp_path / 'files' / error.file
        error.file.parent.mkdir()
        error.file.write_bytes(b'partial')
    _fake_transport(monkeypatch, error)

    with pytest.raises(MediaDownloadError) as info:
        await _downloader(tmp_path).download_file(
            PostDataChunkFile(url=RESOURCE, filename='a.zip'), _noop
        )

    assert info.value.__cause__ is error
    assert info.value.resource_url == RESOURCE
    assert info.value.message == error.message
    if error.file is not None:
        assert not error.file.exists(), 'a partial file must not survive'


async def test_cancelled_transfer_is_a_cancellation_without_the_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    partial = tmp_path / 'files' / 'a.zip'
    partial.parent.mkdir()
    partial.write_bytes(b'partial')
    _fake_transport(
        monkeypatch, DownloadCancelledError(resource_url=RESOURCE, file=partial)
    )

    with pytest.raises(asyncio.CancelledError):
        await _downloader(tmp_path).download_file(
            PostDataChunkFile(url=RESOURCE, filename='a.zip'), _noop
        )

    assert not partial.exists()


# ------------------------------------------------------------------------------
# External videos: yt-dlp must run off the loop, stay cancellable, report safely.


def _status() -> ExternalVideoDownloadStatus:
    return ExternalVideoDownloadStatus(
        name='v',
        total_bytes=100,
        downloaded_bytes=10,
        speed=1.0,
        percentage=10.0,
        delta_bytes=10,
    )


async def test_external_video_runs_off_the_loop_and_progress_lands_on_it(
    tmp_path: Path,
) -> None:
    """The loop thread must stay free; the progress display is touched only from it."""
    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}
    progress: list[tuple[int, MediaProgress]] = []

    class _FakeDownloader:
        def download_video(
            self, *, url: str, destination_directory: Path, progress_hook: object
        ) -> Path:
            del url
            seen['download_thread'] = threading.get_ident()
            cast('object', progress_hook)(_status())  # type: ignore[operator]
            return destination_directory / 'v.mp4'

    def on_progress(step: MediaProgress) -> None:
        progress.append((threading.get_ident(), step))

    result = await _downloader(tmp_path, _FakeDownloader()).download_external_video(
        PostDataChunkExternalVideo(url='https://y/1'), on_progress
    )
    await asyncio.sleep(0.05)  # let call_soon_threadsafe deliver the update

    assert seen['download_thread'] != loop_thread, 'yt-dlp must not run on the loop'
    assert progress == [
        (
            loop_thread,
            MediaProgress(downloaded_bytes=10, total_bytes=100, delta_bytes=10),
        )
    ]
    assert result == Path('external_videos/v.mp4')


async def test_cancellation_aborts_the_worker_thread(tmp_path: Path) -> None:
    """Ctrl+C must stop yt-dlp, not leave it downloading in a zombie thread."""
    started = threading.Event()
    aborted = threading.Event()

    class _LoopingDownloader:
        def download_video(
            self, *, url: str, destination_directory: Path, progress_hook: object
        ) -> Path:
            del url, destination_directory
            started.set()
            try:
                while True:
                    time.sleep(0.01)
                    cast('object', progress_hook)(_status())  # type: ignore[operator]
            except KeyboardInterrupt:
                aborted.set()
                raise ExtVideoInterruptedByUserError from None

    task = asyncio.create_task(
        _downloader(tmp_path, _LoopingDownloader()).download_external_video(
            PostDataChunkExternalVideo(url='https://y/1'), _noop
        )
    )
    await asyncio.to_thread(started.wait, 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert await asyncio.to_thread(aborted.wait, 2), (
        'the worker must abort via KeyboardInterrupt shortly after the cancel'
    )


@pytest.mark.parametrize(
    'error',
    [
        ExtVideoError('https://youtube/watch'),
        ExtVideoError(),
        ExtVideoDownloadError('https://youtube/watch'),
        ExtVideoInfoError('https://youtube/watch'),
    ],
    ids=['base', 'base-without-url', 'download', 'info'],
)
async def test_every_ext_video_error_becomes_a_media_error(
    tmp_path: Path, error: ExtVideoError
) -> None:
    """A removed or restricted video is a failed download, never a raw traceback."""

    class _FailingDownloader:
        def download_video(self, **kwargs: object) -> Path:
            del kwargs
            raise error

    with pytest.raises(MediaDownloadError) as info:
        await _downloader(tmp_path, _FailingDownloader()).download_external_video(
            PostDataChunkExternalVideo(url='https://youtube/watch'), _noop
        )

    assert info.value.__cause__ is error
    assert info.value.resource_url == 'https://youtube/watch'
    assert info.value.retryable is True


async def test_a_gone_video_is_a_media_error_that_says_not_to_retry(
    tmp_path: Path,
) -> None:
    """The retrier spent 5 attempts on a deleted video; the reason must travel with the flag."""
    gone = ExtVideoUnavailableError(
        'https://youtube/watch', 'This video is unavailable'
    )

    class _GoneDownloader:
        def download_video(self, **kwargs: object) -> Path:
            del kwargs
            raise gone

    with pytest.raises(MediaDownloadError) as info:
        await _downloader(tmp_path, _GoneDownloader()).download_external_video(
            PostDataChunkExternalVideo(url='https://youtube/watch'), _noop
        )

    assert info.value.retryable is False
    assert info.value.message == 'External video unavailable: This video is unavailable'
    assert info.value.resource_url == 'https://youtube/watch'


async def test_worker_interrupt_is_a_cancellation(tmp_path: Path) -> None:
    class _InterruptedDownloader:
        def download_video(self, **kwargs: object) -> Path:
            del kwargs
            raise ExtVideoInterruptedByUserError

    with pytest.raises(asyncio.CancelledError):
        await _downloader(tmp_path, _InterruptedDownloader()).download_external_video(
            PostDataChunkExternalVideo(url='https://y/1'), _noop
        )
