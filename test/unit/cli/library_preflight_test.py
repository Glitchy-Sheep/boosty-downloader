"""Library startup keeps the inspected destination and validates syntax first."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from rich.text import Text
from typer.testing import CliRunner

from boosty_downloader.cli import composition_root
from boosty_downloader.cli.commands import download as download_command
from boosty_downloader.infrastructure.library.library_format import (
    LibraryCompatibilityError,
    check_library_compatibility,
)
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.infrastructure.loggers.base import RichLogger


VALID_CONFIG = 'auth:\n  cookie: "session=fake"\n  auth_header: "Bearer fake"\n'
runner = CliRunner()


class _ReachedUpdateCheckError(Exception):
    """Stop after startup without opening network sessions."""


def _plain(output: str) -> str:
    return ' '.join(Text.from_ansi(output).plain.replace('│', ' ').split())


@pytest.mark.parametrize(
    'username',
    [
        '',
        '.',
        '..',
        '../author',
        'author/child',
        r'author\child',
        '/author',
        'C:author',
        ' author',
        'author.',
        'CON',
    ],
)
def test_invalid_author_fails_before_library_or_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, username: str
) -> None:
    monkeypatch.chdir(tmp_path)

    def unexpected_preflight(_root: Path) -> None:
        pytest.fail('Invalid author reached library access')

    monkeypatch.setattr(
        download_command, 'check_library_compatibility', unexpected_preflight
    )

    result = runner.invoke(typer_app, ['--debug', 'download', username])

    assert result.exit_code == 2, result.output
    assert 'single portable directory name' in _plain(result.output)
    assert list(tmp_path.iterdir()) == []


def test_explicit_destination_preflight_does_not_need_config_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'config.yaml').write_text('broken: [', encoding='utf-8')
    observed: list[object] = []

    async def record_download(**kwargs: object) -> None:
        observed.append(kwargs['library_root'])

    monkeypatch.setattr(download_command, '_download_handler', record_download)

    result = runner.invoke(typer_app, ['download', 'author', '-o', './chosen'])

    assert result.exit_code == 0, result.output
    assert observed == [(tmp_path / 'chosen').resolve()]
    assert not (tmp_path / 'chosen').exists()


def test_download_keeps_the_root_that_passed_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / 'config.yaml'
    config.write_text(
        VALID_CONFIG + 'downloading_settings:\n  target_directory: first\n',
        encoding='utf-8',
    )
    inspected: list[Path] = []

    def inspect_and_change_config(root: Path) -> None:
        check_library_compatibility(root)
        inspected.append(root)
        config.write_text(
            VALID_CONFIG + 'downloading_settings:\n  target_directory: second\n',
            encoding='utf-8',
        )

    async def stop_before_network(_logger: RichLogger) -> None:
        assert (inspected[0] / '.boosty-downloader/library.json').is_file()
        raise _ReachedUpdateCheckError

    monkeypatch.setattr(
        download_command, 'check_library_compatibility', inspect_and_change_config
    )
    monkeypatch.setattr(download_command, 'notify_about_updates', stop_before_network)

    result = runner.invoke(typer_app, ['download', 'author'])

    assert isinstance(result.exception, _ReachedUpdateCheckError), result.output
    assert inspected == [(tmp_path / 'first').resolve()]
    assert not (tmp_path / 'second').exists()


def test_invalid_full_config_does_not_initialize_a_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'config.yaml').write_text(
        'auth:\n  cookie: [invalid]\n', encoding='utf-8'
    )

    def unexpected_initialization(_root: Path) -> None:
        pytest.fail('Invalid settings initialized a library')

    monkeypatch.setattr(
        download_command, 'initialize_library', unexpected_initialization
    )

    result = runner.invoke(typer_app, ['download', 'author', '-o', './library'])

    assert result.exit_code == 1
    assert 'auth.cookie' in result.output
    assert not (tmp_path / 'library').exists()


def test_initialization_error_is_reported_before_any_update_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'config.yaml').write_text(VALID_CONFIG, encoding='utf-8')

    def fail_initialization(_root: Path) -> None:
        message = 'Invalid library marker in [bold]named folder'
        raise LibraryCompatibilityError(message)

    async def unexpected_update(_logger: RichLogger) -> None:
        pytest.fail('Rejected library reached the update request')

    monkeypatch.setattr(download_command, 'initialize_library', fail_initialization)
    monkeypatch.setattr(download_command, 'notify_about_updates', unexpected_update)

    result = runner.invoke(typer_app, ['download', 'author', '-o', './library'])

    assert result.exit_code == 1
    assert 'Invalid library marker in [bold]named folder' in _plain(result.output)
    assert '--debug' not in result.output
    assert not (tmp_path / 'library').exists()
    assert (tmp_path / 'config.yaml').read_text(encoding='utf-8') == VALID_CONFIG


def test_unreadable_destination_config_stops_before_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    def unreadable_config(_path: Path) -> None:
        message = 'Configuration is not readable'
        raise PermissionError(message)

    monkeypatch.setattr(composition_root, 'read_download_settings', unreadable_config)

    result = runner.invoke(typer_app, ['--debug', 'download', 'author'])

    assert result.exit_code == 1
    assert 'Cannot determine library folder from config.yaml' in _plain(result.output)
    assert 'Configuration is not readable' in _plain(result.output)
    assert list(tmp_path.iterdir()) == []
