"""Killed downloader processes recover from disk without trusting partial media."""

from __future__ import annotations

import asyncio
import os
import sys
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from aiohttp.test_utils import TestServer
from support.interrupted_download_child import AUTHOR
from support.synthetic_post import (
    POST_ID,
    VIDEO_ID,
    ok_video_chunk,
    synthetic_post,
    text_chunk,
)

from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from asyncio.subprocess import Process
    from collections.abc import AsyncGenerator, Callable

    from yarl import URL

    from boosty_downloader.domain.library import LocatedPost

PROJECT_ROOT = Path(__file__).resolve().parents[2]
VIDEO_BYTES = b'video fixture bytes\x00' * 65536
FIRST_CHUNK_SIZE = 512 * 1024
MEDIA_ID = f'boosty_video:{VIDEO_ID}'
TIMEOUT = 15


@dataclass(slots=True)
class LocalServerState:
    hold_first_transfer: bool = False
    media_requests: list[str] = field(default_factory=list[str])
    finish_first: asyncio.Event = field(default_factory=asyncio.Event)
    first_finished: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(frozen=True, slots=True)
class PartialOutput:
    folder: Path
    final: Path
    workspace: Path
    partial: Path


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    contents: bytes
    modified_ns: int


def _application(state: LocalServerState) -> web.Application:
    async def post(request: web.Request) -> web.Response:
        payload = synthetic_post()
        payload['data'] = [
            text_chunk('A complete page after restart'),
            {
                **ok_video_chunk(),
                'preview': f'http://{request.host}/preview.png',
                'playerUrls': [
                    {'type': 'medium', 'url': f'http://{request.host}/video.mp4'}
                ],
            },
        ]
        return web.json_response(payload)

    async def video(request: web.Request) -> web.StreamResponse:
        state.media_requests.append(request.path)
        if not state.hold_first_transfer or len(state.media_requests) > 1:
            return web.Response(body=VIDEO_BYTES, content_type='video/mp4')
        response = web.StreamResponse(
            headers={
                'Content-Type': 'video/mp4',
                'Content-Length': str(len(VIDEO_BYTES)),
            }
        )
        await response.prepare(request)
        try:
            await response.write(VIDEO_BYTES[:FIRST_CHUNK_SIZE])
            await state.finish_first.wait()
            with suppress(ConnectionResetError):
                await response.write(VIDEO_BYTES[FIRST_CHUNK_SIZE:])
                await response.write_eof()
        finally:
            state.first_finished.set()
        return response

    async def preview(_request: web.Request) -> web.Response:
        return web.Response(body=b'preview bytes', content_type='image/png')

    app = web.Application()
    app.router.add_get(f'/v1/blog/{AUTHOR}/post/{POST_ID}', post)
    app.router.add_get('/video.mp4', video)
    app.router.add_get('/preview.png', preview)
    return app


@asynccontextmanager
async def _child(
    root: Path, api_base: URL, *, published_signal: Path | None = None
) -> AsyncGenerator[Process, None]:
    arguments = [
        sys.executable,
        '-m',
        'support.interrupted_download_child',
        str(root),
        str(api_base),
    ]
    if published_signal is not None:
        arguments.extend(['--published-signal', str(published_signal)])
    environment = {
        **os.environ,
        'PYTHONPATH': os.pathsep.join([str(PROJECT_ROOT), str(PROJECT_ROOT / 'test')]),
    }
    process = await asyncio.create_subprocess_exec(
        *arguments,
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        yield process
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await asyncio.wait_for(process.communicate(), timeout=TIMEOUT)


async def _wait_until(process: Process, ready: Callable[[], bool]) -> None:
    async def poll() -> None:
        while not ready():
            if process.returncode is not None:
                stdout, stderr = await process.communicate()
                message = f'Child exited before the checkpoint: {process.returncode}\n{stdout.decode()}\n{stderr.decode()}'
                raise AssertionError(message)
            await asyncio.sleep(0.02)

    await asyncio.wait_for(poll(), timeout=TIMEOUT)


async def _kill(process: Process) -> None:
    process.kill()
    await asyncio.wait_for(process.wait(), timeout=TIMEOUT)
    assert process.returncode is not None
    assert process.returncode != 0


async def _finish(process: Process) -> str:
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=TIMEOUT)
    assert process.returncode == 0, f'{stdout.decode()}\n{stderr.decode()}'
    return stdout.decode().strip()


def _located(root: Path) -> LocatedPost:
    located = JsonPostStore(root).find_post(AUTHOR, POST_ID)
    assert located is not None
    assert located.record is not None
    return located


def _find_partial(root: Path) -> PartialOutput | None:
    located = JsonPostStore(root).find_post(AUTHOR, POST_ID)
    if located is None or located.record is None:
        return None
    entry = located.record.media[MEDIA_ID]
    if entry.path is None:
        return None
    folder = root / located.folder
    final = folder / entry.path
    for workspace in final.parent.glob('.boosty-*.part'):
        partial = workspace / 'download.tmp'
        if (
            (workspace / '.owner').is_file()
            and partial.is_file()
            and 0 < partial.stat().st_size <= FIRST_CHUNK_SIZE
        ):
            return PartialOutput(folder, final, workspace, partial)
    return None


def _foreign_files(folder: Path, media_parent: Path) -> dict[Path, FileSnapshot]:
    files = {
        folder / 'viewer.json': b'{"position": 42}',
        folder / 'notes.txt': b'Personal notes',
        media_parent / 'unrelated.mp4': b'Existing unrelated video',
        media_parent / 'manual.part': b'A manual incomplete download',
        media_parent / '.boosty-user.part' / 'download.tmp': b'Foreign workspace bytes',
    }
    for path, contents in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    return {
        path: FileSnapshot(path.read_bytes(), path.stat().st_mtime_ns) for path in files
    }


def _assert_foreign_untouched(files: dict[Path, FileSnapshot]) -> None:
    assert {
        path: FileSnapshot(path.read_bytes(), path.stat().st_mtime_ns) for path in files
    } == files


def _assert_completed(root: Path, expected_path: Path) -> None:
    located = _located(root)
    assert located.record is not None
    entry = located.record.media[MEDIA_ID]
    assert entry.status is MediaStatus.downloaded
    assert entry.size == len(VIDEO_BYTES)
    assert entry.path is not None
    assert root / located.folder / entry.path == expected_path
    assert expected_path.read_bytes() == VIDEO_BYTES
    assert located.record.sync.page_template == PAGE_TEMPLATE_VERSION
    page = (root / located.folder / 'post.html').read_text(encoding='utf-8')
    assert 'A complete page after restart' in page
    assert '<video' in page
    assert 'not downloaded' not in page


async def test_killed_transfer_leaves_no_final_and_restart_downloads_once(
    tmp_path: Path,
) -> None:
    root = tmp_path / 'library'
    state = LocalServerState(hold_first_transfer=True)
    async with TestServer(_application(state)) as server:
        try:
            async with _child(root, server.make_url('/')) as process:
                await _wait_until(process, lambda: _find_partial(root) is not None)
                output = _find_partial(root)
                assert output is not None
                assert not output.final.exists()
                foreign = _foreign_files(output.folder, output.final.parent)
                await _kill(process)
            state.finish_first.set()
            await asyncio.wait_for(state.first_finished.wait(), timeout=TIMEOUT)
            assert not output.final.exists()
            partial_bytes = output.partial.read_bytes()
            assert 0 < len(partial_bytes) <= FIRST_CHUNK_SIZE
            assert partial_bytes == VIDEO_BYTES[: len(partial_bytes)]
            located = _located(root)
            assert located.record is not None
            entry = located.record.media[MEDIA_ID]
            assert entry.status is MediaStatus.pending
            assert entry.size is None
            _assert_foreign_untouched(foreign)

            async with _child(root, server.make_url('/')) as retry:
                assert await _finish(retry) == f'downloaded {len(VIDEO_BYTES)}'

            assert state.media_requests == ['/video.mp4', '/video.mp4']
            assert not output.workspace.exists()
            _assert_completed(root, output.final)
            _assert_foreign_untouched(foreign)
        finally:
            state.finish_first.set()


async def test_killed_after_publication_recovers_without_another_media_request(
    tmp_path: Path,
) -> None:
    root = tmp_path / 'library'
    ready = tmp_path / 'published.signal'
    state = LocalServerState()
    async with TestServer(_application(state)) as server:
        async with _child(
            root, server.make_url('/'), published_signal=ready
        ) as process:
            await _wait_until(process, ready.exists)
            located = _located(root)
            assert located.record is not None
            entry = located.record.media[MEDIA_ID]
            assert entry.status is MediaStatus.pending
            assert entry.size is None
            assert entry.path is not None
            final = root / located.folder / entry.path
            assert final.read_bytes() == VIDEO_BYTES
            foreign = _foreign_files(root / located.folder, final.parent)
            await _kill(process)
        assert not (root / located.folder / 'post.html').exists()
        modified_ns = final.stat().st_mtime_ns

        async with _child(root, server.make_url('/')) as retry:
            assert await _finish(retry) == 'downloaded 0'

        assert state.media_requests == ['/video.mp4']
        assert final.stat().st_mtime_ns == modified_ns
        _assert_completed(root, final)
        _assert_foreign_untouched(foreign)
