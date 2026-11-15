"""Reserve external media on the event loop and own its worker output."""

from __future__ import annotations

from asyncio import CancelledError, get_running_loop, wait
from contextlib import contextmanager
from functools import partial
from stat import S_ISREG
from threading import Event
from typing import TYPE_CHECKING, TypeVar

from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.media_output_paths import create_media_parent
from boosty_downloader.infrastructure.media_publication import publish_completed_file
from boosty_downloader.infrastructure.media_workspace import (
    cleanup_media_workspaces,
    temporary_media_workspace,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideoDownloadProgressHook,
        ExternalVideoDownloadStatus,
        ExternalVideosDownloader,
    )
    from boosty_downloader.infrastructure.media_publication import PublishedFile
    from boosty_downloader.infrastructure.media_transfer import (
        MediaTarget,
        ReserveMediaPath,
    )
    from boosty_downloader.infrastructure.media_workspace import MediaWorkspace

_Result = TypeVar('_Result')


async def download_reserved_video(
    downloader: ExternalVideosDownloader,
    url: str,
    reserve: ReserveMediaPath,
    progress_hook: ExternalVideoDownloadProgressHook | None,
) -> PublishedFile:
    """Persist destinations before writing; wait for cancellation before cleanup."""
    stopped = Event()
    prepared = await _run_worker(partial(downloader.prepare_video, url), stopped)
    target = reserve(prepared.filename)
    with _owned_workspace(target) as workspace:
        transfer = partial(
            downloader.download_prepared,
            prepared,
            workspace.directory,
            _progress_relay(stopped, progress_hook),
        )
        source = await _run_worker(transfer, stopped)
        return _publish_output(source, workspace, target, prepared.filename, reserve)


@contextmanager
def _owned_workspace(target: MediaTarget) -> Generator[MediaWorkspace, None, None]:
    cleanup_media_workspaces(
        target.library_root,
        target.post_folder,
        target.relative_path,
        media_id=target.media_id,
    )
    with temporary_media_workspace(
        target.library_root,
        target.post_folder,
        target.relative_path,
        media_id=target.media_id,
    ) as workspace:
        yield workspace


def _publish_output(
    source: Path,
    workspace: MediaWorkspace,
    target: MediaTarget,
    filename: str,
    reserve: ReserveMediaPath,
) -> PublishedFile:
    _validate_output(source, workspace.directory)
    if source.name != filename:
        target = _same_owner(target, reserve(source.name))
    destination = create_media_parent(
        target.library_root, target.post_folder, target.relative_path
    )
    return publish_completed_file(source, destination)


def _progress_relay(
    stopped: Event, callback: ExternalVideoDownloadProgressHook | None
) -> ExternalVideoDownloadProgressHook:
    loop = get_running_loop()

    def relay(status: ExternalVideoDownloadStatus) -> None:
        if stopped.is_set():
            raise KeyboardInterrupt
        if callback is not None:
            loop.call_soon_threadsafe(callback, status)

    return relay


async def _run_worker(operation: Callable[[], _Result], stopped: Event) -> _Result:
    worker = get_running_loop().run_in_executor(None, operation)
    cancellation: CancelledError | None = None
    while True:
        try:
            await wait({worker})
        except CancelledError as error:
            stopped.set()
            if cancellation is None:
                cancellation = error
        if worker.done():
            break
    if cancellation is not None:
        if not worker.cancelled():
            raise cancellation from worker.exception()
        raise cancellation
    return worker.result()


def _validate_output(path: Path, workspace: Path) -> None:
    # yt-dlp output belongs entirely to this transfer's private directory.
    try:
        relative = path.relative_to(workspace)
    except ValueError as error:
        message = 'External video output escapes its temporary directory'
        raise ValueError(message) from error
    if '..' in relative.parts:
        message = 'External video output escapes its temporary directory'
        raise ValueError(message)
    current = workspace
    for component in relative.parts:
        current /= component
        if is_link(current.lstat()):
            message = 'External video output traverses a filesystem link'
            raise ValueError(message)
    if not S_ISREG(path.lstat().st_mode):
        message = 'External video output is not a regular file'
        raise ValueError(message)


def _same_owner(original: MediaTarget, updated: MediaTarget) -> MediaTarget:
    if (
        updated.library_root != original.library_root
        or updated.post_folder != original.post_folder
        or updated.media_id != original.media_id
    ):
        message = 'A postprocessed video must retain its reservation owner'
        raise ValueError(message)
    return updated
