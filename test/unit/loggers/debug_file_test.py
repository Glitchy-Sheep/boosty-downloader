"""Diagnostic sinks belong to one command, including repeated in-process runs."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest
from aiohttp import ClientError
from rich.logging import RichHandler
from typer.testing import CliRunner

from boosty_downloader.cli.commands import check as check_command
from boosty_downloader.cli.commands import download as download_command
from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPIUnauthorizedError,
)
from boosty_downloader.infrastructure.loggers.debug_file import (
    DEBUG_LOG_FILENAME,
    debug_logging,
    is_debug_enabled,
)
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def test_file_diagnostics_close_the_file_and_restore_handlers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    logger = logging.getLogger('boosty_downloader')
    handlers = logger.handlers.copy()
    level = logger.level

    with debug_logging(enabled=True):
        assert is_debug_enabled()
        handler = next(item for item in logger.handlers if item not in handlers)
        assert isinstance(handler, RichHandler)
        stream = handler.console.file
        logger.debug('Diagnostic detail')

    assert stream.closed
    assert not is_debug_enabled()
    assert logger.handlers == handlers
    assert logger.level == level
    assert 'Diagnostic detail' in (tmp_path / DEBUG_LOG_FILENAME).read_text(
        encoding='utf-8'
    )


def test_console_diagnostics_leave_existing_file_unchanged_and_do_not_duplicate_info(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / DEBUG_LOG_FILENAME
    path.write_text('Previous diagnostic', encoding='utf-8')
    before = path.stat().st_mtime_ns
    logger = logging.getLogger('Boosty_Downloader')
    handlers = logger.handlers.copy()

    with debug_logging(enabled=True, read_only=True):
        assert not is_debug_enabled()
        logger.debug('Console detail')
        logger.info('One normal message')

    captured = capsys.readouterr()
    assert 'Console detail' in captured.err
    assert 'One normal message' not in captured.err
    assert logger.handlers == handlers
    assert path.read_text(encoding='utf-8') == 'Previous diagnostic'
    assert path.stat().st_mtime_ns == before


def test_debug_network_error_is_recorded_before_the_file_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    async def fail(**_kwargs: object) -> None:
        message = 'ordinary failure'
        raise ClientError(message)

    monkeypatch.setattr(check_command, '_check_handler', fail)
    result = runner.invoke(typer_app, ['--debug', 'check', 'creator'])

    assert result.exit_code == 1
    assert 'Details written to' in result.output
    content = (tmp_path / DEBUG_LOG_FILENAME).read_text(encoding='utf-8')
    assert 'ordinary failure' in content
    assert 'Traceback' in content
    assert not is_debug_enabled()


@pytest.mark.parametrize('debug', [False, True])
def test_preview_network_error_uses_console_hint_after_an_ordinary_debug_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, debug: bool
) -> None:
    monkeypatch.chdir(tmp_path)

    async def fail(**_kwargs: object) -> None:
        message = 'preview failure'
        raise ClientError(message)

    monkeypatch.setattr(check_command, '_check_handler', fail)
    monkeypatch.setattr(download_command, '_download_handler', fail)
    runner.invoke(typer_app, ['--debug', 'check', 'creator'])
    path = tmp_path / DEBUG_LOG_FILENAME
    before = path.read_bytes()
    modified_ns = path.stat().st_mtime_ns
    logger = logging.getLogger('boosty_downloader')
    handlers = logger.handlers.copy()

    result = runner.invoke(
        typer_app, [*(['--debug'] if debug else []), 'download', 'creator', '--dry-run']
    )

    assert result.exit_code == 1
    assert 'Dry-run writes no diagnostic file' in result.output
    assert 'Details written to' not in result.output
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == modified_ns
    assert logger.handlers == handlers
    if debug:
        assert 'Traceback' in result.output


def test_errors_delegated_to_main_keep_diagnostics_before_context_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    async def fail(**_kwargs: object) -> None:
        raise BoostyAPIUnauthorizedError

    monkeypatch.setattr(check_command, '_check_handler', fail)
    result = runner.invoke(typer_app, ['--debug', 'check', 'creator'])

    assert isinstance(result.exception, BoostyAPIUnauthorizedError)
    assert 'BoostyAPIUnauthorizedError' in (tmp_path / DEBUG_LOG_FILENAME).read_text(
        encoding='utf-8'
    )
    assert not is_debug_enabled()
