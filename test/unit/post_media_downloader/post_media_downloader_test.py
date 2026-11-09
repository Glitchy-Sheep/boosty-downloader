"""The post facade preserves reserved results, progress and transport failures."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
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
    DownloadingStatus,
    DownloadIOFailureError,
    DownloadUnexpectedStatusError,
    ReservedDownloadFileConfig,
)
from boosty_downloader.infrastructure.media_publication import PublishedFile
from boosty_downloader.infrastructure.media_transfer import MediaTarget
from boosty_downloader.infrastructure.post_media_downloader import (
    MediaDownloadError,
    MediaProgress,
    PostMediaDownloader,
)

if TYPE_CHECKING:
    from aiohttp_retry import RetryClient

    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideoDownloadProgressHook,
        ExternalVideosDownloader,
    )
    from boosty_downloader.infrastructure.media_transfer import ReserveMediaPath

RESOURCE = 'https://cdn.example/file'
POST_FOLDER = 'author/post'


def _downloader(external: object = None) -> PostMediaDownloader:
    return PostMediaDownloader(
        http=cast('RetryClient', None),
        external_videos=cast('ExternalVideosDownloader', external),
    )


def _reserve(
    root: Path, folder: str = 'files', media_id: str = 'file:f1'
) -> ReserveMediaPath:
    def reserve(name: str) -> MediaTarget:
        return MediaTarget(root, POST_FOLDER, f'{folder}/{name}', media_id)

    return reserve


def _noop(_progress: MediaProgress) -> None:
    pass


def _fake_transport(
    monkeypatch: pytest.MonkeyPatch, error: DownloadError | None = None
) -> list[ReservedDownloadFileConfig]:
    configs: list[ReservedDownloadFileConfig] = []

    async def fake_download(config: ReservedDownloadFileConfig) -> PublishedFile:
        configs.append(config)
        if error is not None:
            raise error
        target = config.reserve(config.filename)
        config.on_status_update(
            DownloadingStatus(
                name=config.filename,
                total_bytes=100,
                total_downloaded_bytes=40,
                downloaded_bytes=40,
            )
        )
        return PublishedFile(
            path=target.library_root / target.post_folder / target.relative_path,
            size=40,
        )

    monkeypatch.setattr(module, 'download_reserved_file', fake_download)
    return configs


async def _download_every_kind(
    media: PostMediaDownloader, root: Path
) -> list[PublishedFile]:
    return [
        await media.download_image(
            PostDataChunkImage(id='i1', url='https://cdn/image/40f9e868'),
            _noop,
            reserve=_reserve(root, 'images', 'image:i1'),
        ),
        await media.download_file(
            PostDataChunkFile(id='f1', url='u', filename='any.appimage'),
            _noop,
            reserve=_reserve(root),
        ),
        await media.download_audio(
            PostDataChunkAudio(id='a1', url='u', title='song.mp3'),
            _noop,
            reserve=_reserve(root, 'audio', 'audio:a1'),
        ),
        await media.download_boosty_video(
            PostDataChunkBoostyVideo(
                id='a2dd6942-7297', title='Update v1.2', url='u', quality='medium'
            ),
            _noop,
            reserve=_reserve(root, 'boosty_videos', 'boosty_video:a2dd6942-7297'),
        ),
    ]


async def test_success_keeps_the_transports_reserved_paths_and_sizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_transport(monkeypatch)

    saved = await _download_every_kind(_downloader(), tmp_path)

    assert [result.path.relative_to(tmp_path / POST_FOLDER) for result in saved] == [
        Path('images/40f9e868'),
        Path('files/any.appimage'),
        Path('audio/song.mp3'),
        Path('boosty_videos/Update v1.2 (a2dd6942)'),
    ]
    assert all(result.size == 40 for result in saved)


async def test_extension_policy_follows_the_name_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configs = _fake_transport(monkeypatch)

    await _download_every_kind(_downloader(), tmp_path)

    assert {config.filename: config.guess_extension for config in configs} == {
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

    await _downloader().download_file(
        PostDataChunkFile(id='f1', url='u', filename='a.zip'),
        seen.append,
        reserve=_reserve(tmp_path),
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
async def test_transport_failure_keeps_its_cause_and_never_deletes_a_reported_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: DownloadError
) -> None:
    if error.file is not None:
        error.file = tmp_path / error.file
        error.file.write_bytes(b'user file')
    _fake_transport(monkeypatch, error)

    with pytest.raises(MediaDownloadError) as caught:
        await _downloader().download_file(
            PostDataChunkFile(id='f1', url=RESOURCE, filename='a.zip'),
            _noop,
            reserve=_reserve(tmp_path),
        )

    assert caught.value.__cause__ is error
    assert caught.value.resource_url == RESOURCE
    assert caught.value.message == error.message
    assert caught.value.file is None
    if error.file is not None:
        assert error.file.read_bytes() == b'user file'


async def test_cancelled_transfer_is_a_cancellation_and_preserves_foreign_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    occupied = tmp_path / 'a.zip'
    occupied.write_bytes(b'user file')
    failure = DownloadCancelledError(resource_url=RESOURCE, file=occupied)
    _fake_transport(monkeypatch, failure)

    with pytest.raises(asyncio.CancelledError) as caught:
        await _downloader().download_file(
            PostDataChunkFile(id='f1', url=RESOURCE, filename='a.zip'),
            _noop,
            reserve=_reserve(tmp_path),
        )

    assert caught.value.__cause__ is failure
    assert occupied.read_bytes() == b'user file'


async def test_reservation_failure_is_not_reclassified_as_a_media_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = OSError('Saving reservation failed')
    _fake_transport(monkeypatch)

    def reserve(_name: str) -> MediaTarget:
        raise failure

    with pytest.raises(OSError, match='Saving reservation failed') as caught:
        await _downloader().download_file(
            PostDataChunkFile(id='f1', url=RESOURCE, filename='a.zip'),
            _noop,
            reserve=reserve,
        )

    assert caught.value is failure


def _status() -> ExternalVideoDownloadStatus:
    return ExternalVideoDownloadStatus(
        name='v',
        total_bytes=100,
        downloaded_bytes=10,
        speed=1.0,
        percentage=10.0,
        delta_bytes=10,
    )


class _ExternalAdapter:
    def __init__(self, error: ExtVideoError | None = None) -> None:
        self.error = error

    async def download_reserved_video(
        self,
        url: str,
        reserve: ReserveMediaPath,
        *,
        progress_hook: ExternalVideoDownloadProgressHook | None = None,
    ) -> PublishedFile:
        del url
        if self.error is not None:
            raise self.error
        target = reserve('video.mp4')
        if progress_hook is not None:
            progress_hook(_status())
        return PublishedFile(
            target.library_root / target.post_folder / target.relative_path, 100
        )


@dataclass(frozen=True)
class _ObservedProgress:
    thread_id: int
    progress: MediaProgress


async def test_external_progress_stays_on_the_adapters_event_loop(
    tmp_path: Path,
) -> None:
    seen: list[_ObservedProgress] = []

    def progress(step: MediaProgress) -> None:
        seen.append(_ObservedProgress(threading.get_ident(), step))

    result = await _downloader(_ExternalAdapter()).download_external_video(
        PostDataChunkExternalVideo(url='https://y/1'),
        progress,
        reserve=_reserve(tmp_path, 'external_videos', 'external_video:https://y/1'),
    )

    assert seen == [
        _ObservedProgress(
            threading.get_ident(),
            MediaProgress(downloaded_bytes=10, total_bytes=100, delta_bytes=10),
        )
    ]
    assert result == PublishedFile(
        tmp_path / POST_FOLDER / 'external_videos/video.mp4', 100
    )


async def test_cancellation_waits_for_the_external_adapter_to_exit(
    tmp_path: Path,
) -> None:
    started = asyncio.Event()
    stopped = asyncio.Event()

    class _WaitingAdapter:
        async def download_reserved_video(
            self, *_args: object, **_kwargs: object
        ) -> PublishedFile:
            started.set()
            try:
                await asyncio.Future[None]()
            finally:
                stopped.set()
            pytest.fail('The adapter must be cancelled')

    task = asyncio.create_task(
        _downloader(_WaitingAdapter()).download_external_video(
            PostDataChunkExternalVideo(url='https://y/1'),
            _noop,
            reserve=_reserve(tmp_path),
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)

    assert stopped.is_set()


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
    with pytest.raises(MediaDownloadError) as caught:
        await _downloader(_ExternalAdapter(error)).download_external_video(
            PostDataChunkExternalVideo(url='https://youtube/watch'),
            _noop,
            reserve=_reserve(tmp_path),
        )

    assert caught.value.__cause__ is error
    assert caught.value.resource_url == 'https://youtube/watch'
    assert caught.value.retryable is True


async def test_a_gone_video_is_a_media_error_that_says_not_to_retry(
    tmp_path: Path,
) -> None:
    gone = ExtVideoUnavailableError(
        'https://youtube/watch', 'This video is unavailable'
    )

    with pytest.raises(MediaDownloadError) as caught:
        await _downloader(_ExternalAdapter(gone)).download_external_video(
            PostDataChunkExternalVideo(url='https://youtube/watch'),
            _noop,
            reserve=_reserve(tmp_path),
        )

    assert caught.value.retryable is False
    assert (
        caught.value.message == 'External video unavailable: This video is unavailable'
    )
    assert caught.value.resource_url == 'https://youtube/watch'


async def test_worker_interrupt_is_a_cancellation(tmp_path: Path) -> None:
    interrupted = ExtVideoInterruptedByUserError()
    with pytest.raises(asyncio.CancelledError) as caught:
        await _downloader(_ExternalAdapter(interrupted)).download_external_video(
            PostDataChunkExternalVideo(url='https://y/1'),
            _noop,
            reserve=_reserve(tmp_path),
        )

    assert caught.value.__cause__ is interrupted
