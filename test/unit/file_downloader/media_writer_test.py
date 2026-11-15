"""Media writers finish executor operations before releasing temporary output."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from threading import Event
from typing import TYPE_CHECKING, Literal, cast

import pytest

from boosty_downloader.infrastructure import media_writer
from boosty_downloader.infrastructure.media_publication import publish_completed_file
from boosty_downloader.infrastructure.media_workspace import temporary_media_workspace
from boosty_downloader.infrastructure.media_writer import open_media_writer

if TYPE_CHECKING:
    from collections.abc import Awaitable
    from pathlib import Path
    from typing import BinaryIO

IOPhase = Literal['open', 'write', 'close']
MEDIA_BYTES = b'Completed media bytes'


@dataclass
class _WorkerGate:
    loop: asyncio.AbstractEventLoop = field(default_factory=asyncio.get_running_loop)
    entered: asyncio.Event = field(default_factory=asyncio.Event)
    release: Event = field(default_factory=Event)

    def block(self) -> None:
        self.loop.call_soon_threadsafe(self.entered.set)
        if not self.release.wait(timeout=5):
            message = 'Test did not release the worker'
            raise TimeoutError(message)


@dataclass
class _FileProbe:
    gates: dict[IOPhase, _WorkerGate] = field(
        default_factory=dict[IOPhase, _WorkerGate]
    )
    failures: dict[IOPhase, OSError] = field(default_factory=dict[IOPhase, OSError])
    file: BinaryIO | None = None

    def _pause(self, phase: IOPhase) -> None:
        if gate := self.gates.get(phase):
            gate.block()

    def _raise_failure(self, phase: IOPhase) -> None:
        if failure := self.failures.get(phase):
            raise failure

    def open(self, path: Path) -> BinaryIO:
        if 'open' in self.failures:
            self._pause('open')
            self._raise_failure('open')
        self.file = path.open('xb')
        self._pause('open')
        return cast('BinaryIO', self)

    def write(self, content: bytes) -> int:
        assert self.file is not None
        self._pause('write')
        self._raise_failure('write')
        return self.file.write(content)

    def close(self) -> None:
        assert self.file is not None
        self._pause('close')
        self.file.close()
        self._raise_failure('close')


async def _event_loop_turn() -> None:
    loop = asyncio.get_running_loop()
    ready = loop.create_future()
    loop.call_soon(ready.set_result, None)
    await ready


async def _capture_cancellation(
    operation: Awaitable[object], cancellations: list[asyncio.CancelledError]
) -> None:
    try:
        await operation
    except asyncio.CancelledError as error:
        cancellations.append(error)
        raise


async def _write_file(path: Path) -> None:
    async with open_media_writer(path) as writer:
        await writer.write(MEDIA_BYTES)


async def _write_and_publish(source: Path, destination: Path) -> None:
    await _write_file(source)
    publish_completed_file(source, destination)


@pytest.mark.parametrize('chunks', [[], [b'first ', b'second', b'']])
async def test_closed_output_is_complete_before_publication(
    tmp_path: Path, chunks: list[bytes]
) -> None:
    source = tmp_path / 'download.tmp'
    destination = tmp_path / 'media.bin'

    async with open_media_writer(source) as writer:
        for chunk in chunks:
            await writer.write(chunk)
        assert not destination.exists()
    result = publish_completed_file(source, destination)

    assert destination.read_bytes() == b''.join(chunks)
    assert result.size == sum(map(len, chunks))


async def test_open_does_not_replace_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / 'user.bin'
    path.write_bytes(b'keep')

    with pytest.raises(FileExistsError):
        await _write_file(path)

    assert path.read_bytes() == b'keep'


async def test_open_does_not_create_parent_directories(tmp_path: Path) -> None:
    parent = tmp_path / 'absent'

    with pytest.raises(FileNotFoundError):
        await _write_file(parent / 'download.tmp')

    assert not parent.exists()


async def test_open_failure_never_enters_writer_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = PermissionError('Cannot open temporary file')
    probe = _FileProbe(failures={'open': failure})
    monkeypatch.setattr(media_writer, '_open_file', probe.open)

    with pytest.raises(PermissionError) as caught:
        async with open_media_writer(tmp_path / 'download.tmp'):
            pytest.fail('A failed open cannot yield a writer')

    assert caught.value is failure
    assert probe.file is None


async def test_write_failure_closes_the_file_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = OSError('Disk write failed')
    probe = _FileProbe(failures={'write': failure})
    monkeypatch.setattr(media_writer, '_open_file', probe.open)

    with pytest.raises(OSError, match='Disk write failed') as caught:
        await _write_file(tmp_path / 'download.tmp')

    assert caught.value is failure
    assert probe.file is not None
    assert probe.file.closed


async def test_close_failure_prevents_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = OSError('Buffered output could not be flushed')
    probe = _FileProbe(failures={'close': failure})
    monkeypatch.setattr(media_writer, '_open_file', probe.open)
    source, destination = tmp_path / 'download.tmp', tmp_path / 'media.bin'

    with pytest.raises(OSError, match='Buffered output could not be flushed') as caught:
        await _write_and_publish(source, destination)

    assert caught.value is failure
    assert not destination.exists()


async def test_body_failure_survives_close_failure_and_logs_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    failure = RuntimeError('Response stream failed')
    probe = _FileProbe(failures={'close': OSError('Closing output failed')})
    monkeypatch.setattr(media_writer, '_open_file', probe.open)

    with pytest.raises(RuntimeError) as caught:
        async with open_media_writer(tmp_path / 'download.tmp'):
            raise failure

    assert caught.value is failure
    assert probe.file is not None
    assert probe.file.closed
    assert any(record.levelno >= logging.WARNING for record in caplog.records)
    assert 'Closing output failed' in caplog.text


@pytest.mark.parametrize('phase', ['open', 'write', 'close'])
async def test_repeated_cancellation_waits_for_io_and_close_before_workspace_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: IOPhase
) -> None:
    gate = _WorkerGate()
    probe = _FileProbe(gates={phase: gate})
    monkeypatch.setattr(media_writer, '_open_file', probe.open)
    directories: list[Path] = []

    async def transfer() -> None:
        with temporary_media_workspace(
            tmp_path, 'author/post', 'files/media.bin', media_id='file:media'
        ) as workspace:
            directories.append(workspace.directory)
            source = workspace.directory / 'download.tmp'
            await _write_file(source)
            publish_completed_file(source, workspace.destination)

    cancellations: list[asyncio.CancelledError] = []
    task = asyncio.create_task(_capture_cancellation(transfer(), cancellations))
    try:
        await asyncio.wait_for(gate.entered.wait(), timeout=2)
        for message in ['first cancellation', 'second cancellation']:
            task.cancel(message)
            await _event_loop_turn()
            assert not task.done()
            assert directories[0].is_dir()
            assert probe.file is not None
            assert not probe.file.closed
    finally:
        gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)

    assert len(cancellations) == 1
    assert cancellations[0].args == ('first cancellation',)

    assert probe.file is not None
    assert probe.file.closed
    assert not directories[0].exists()
    assert not (tmp_path / 'author/post/files/media.bin').exists()


@pytest.mark.parametrize('phase', ['open', 'write', 'close'])
async def test_cancellation_remains_primary_when_the_worker_also_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, phase: IOPhase
) -> None:
    gate = _WorkerGate()
    failure = OSError('Worker failed after cancellation')
    probe = _FileProbe(gates={phase: gate}, failures={phase: failure})
    monkeypatch.setattr(media_writer, '_open_file', probe.open)
    cancellations: list[asyncio.CancelledError] = []
    task = asyncio.create_task(
        _capture_cancellation(_write_file(tmp_path / 'download.tmp'), cancellations)
    )
    try:
        await asyncio.wait_for(gate.entered.wait(), timeout=2)
        task.cancel('Stop transfer')
        await _event_loop_turn()
        assert not task.done()
    finally:
        gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)

    assert len(cancellations) == 1
    assert cancellations[0].args == ('Stop transfer',)

    assert cancellations[0].__cause__ is failure
    if probe.file is not None:
        assert probe.file.closed


async def test_cancellation_during_close_keeps_the_prior_body_error_as_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    gate = _WorkerGate()
    failure = RuntimeError('Response stream failed')
    probe = _FileProbe(
        gates={'close': gate}, failures={'close': OSError('Close also failed')}
    )
    monkeypatch.setattr(media_writer, '_open_file', probe.open)

    async def transfer() -> None:
        async with open_media_writer(tmp_path / 'download.tmp'):
            raise failure

    cancellations: list[asyncio.CancelledError] = []
    task = asyncio.create_task(_capture_cancellation(transfer(), cancellations))
    try:
        await asyncio.wait_for(gate.entered.wait(), timeout=2)
        task.cancel('Stop closing')
        await _event_loop_turn()
        assert not task.done()
    finally:
        gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)

    assert len(cancellations) == 1
    assert cancellations[0].args == ('Stop closing',)

    assert cancellations[0].__cause__ is failure
    assert probe.file is not None
    assert probe.file.closed
    assert 'Close also failed' in caplog.text


async def test_cancellation_during_close_does_not_replace_the_initial_cancellation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    write_gate, close_gate = _WorkerGate(), _WorkerGate()
    failure = OSError('Write failed after cancellation')
    probe = _FileProbe(
        gates={'write': write_gate, 'close': close_gate},
        failures={'write': failure, 'close': OSError('Close also failed')},
    )
    monkeypatch.setattr(media_writer, '_open_file', probe.open)
    cancellations: list[asyncio.CancelledError] = []
    task = asyncio.create_task(
        _capture_cancellation(_write_file(tmp_path / 'download.tmp'), cancellations)
    )
    try:
        await asyncio.wait_for(write_gate.entered.wait(), timeout=2)
        task.cancel('First cancellation')
        await _event_loop_turn()
        write_gate.release.set()
        await asyncio.wait_for(close_gate.entered.wait(), timeout=2)
        task.cancel('Cancellation during close')
        await _event_loop_turn()
        assert not task.done()
    finally:
        write_gate.release.set()
        close_gate.release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)

    assert len(cancellations) == 1
    assert cancellations[0].args == ('First cancellation',)

    assert cancellations[0].__cause__ is failure
    assert probe.file is not None
    assert probe.file.closed
    assert 'Close also failed' in caplog.text


async def test_short_write_fails_and_closes_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = _FileProbe()
    monkeypatch.setattr(media_writer, '_open_file', probe.open)

    def short_write(_content: bytes) -> int:
        return 1

    monkeypatch.setattr(probe, 'write', short_write)
    with pytest.raises(OSError, match='Incomplete temporary media write'):
        await _write_file(tmp_path / 'download.tmp')

    assert probe.file is not None
    assert probe.file.closed


async def test_completed_worker_does_not_hide_pending_cancellation() -> None:
    completed: asyncio.Future[int] = asyncio.get_running_loop().create_future()
    completed.set_result(1)

    async def read_result() -> int:
        task = asyncio.current_task()
        assert task is not None
        task.cancel('Already cancelled')
        return await media_writer._finish_io(completed)  # pyright: ignore[reportPrivateUsage]

    cancellations: list[asyncio.CancelledError] = []
    with pytest.raises(asyncio.CancelledError):
        await asyncio.create_task(_capture_cancellation(read_result(), cancellations))

    assert len(cancellations) == 1
    assert cancellations[0].args == ('Already cancelled',)
