"""Transient Windows reader locks preserve complete old or new record bytes."""

from __future__ import annotations

import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import pytest

from boosty_downloader.infrastructure.library import _atomic_write


@pytest.mark.parametrize('windows_error', [5, 32, 33])
def test_transient_reader_lock_retries_complete_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows_error: int
) -> None:
    target = tmp_path / 'post.json'
    target.write_bytes(b'old complete record')
    replace = Path.replace
    failures = 2

    def while_locked(source: Path, destination: Path) -> Path:
        nonlocal failures
        assert target.read_bytes() == b'old complete record'
        assert source.read_bytes() == b'new complete record'
        if failures:
            failures -= 1
            error = PermissionError('A reader has the record open')
            error.winerror = windows_error  # type: ignore[attr-defined]
            raise error
        return replace(source, destination)

    monkeypatch.setattr(Path, 'replace', while_locked)
    _atomic_write.write_atomically(target, b'new complete record')

    assert failures == 0
    assert target.read_bytes() == b'new complete record'
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize('windows_error', [None, 5, 32, 33])
def test_persistent_denial_preserves_record_and_removes_owned_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, windows_error: int | None
) -> None:
    target = tmp_path / 'post.json'
    target.write_bytes(b'old complete record')
    error = PermissionError('The record cannot be replaced')
    if windows_error is not None:
        error.winerror = windows_error  # type: ignore[attr-defined]

    def deny(_source: Path, _destination: Path) -> Path:
        raise error

    monkeypatch.setattr(Path, 'replace', deny)
    with pytest.raises(PermissionError) as raised:
        _atomic_write.write_atomically(target, b'new complete record')

    assert raised.value is error
    assert target.read_bytes() == b'old complete record'
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows open-file replacement')
def test_real_reader_can_close_while_complete_record_is_published(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / 'post.json'
    target.write_bytes(b'old complete record')
    blocked = Event()
    replace = Path.replace

    def observe_lock(source: Path, destination: Path) -> Path:
        try:
            return replace(source, destination)
        except PermissionError:
            blocked.set()
            raise

    monkeypatch.setattr(Path, 'replace', observe_lock)
    with ThreadPoolExecutor(max_workers=1) as executor:
        with target.open('rb') as reader:
            pending = executor.submit(
                _atomic_write.write_atomically, target, b'new complete record'
            )
            assert blocked.wait(timeout=5)
            assert reader.read() == b'old complete record'
        pending.result(timeout=5)

    assert target.read_bytes() == b'new complete record'
    assert list(tmp_path.iterdir()) == [target]
