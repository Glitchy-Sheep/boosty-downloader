"""CLI smoke: the real typer app parses argv - a net for command wiring.

Unlike exit_codes_test.py (which stubs the app), these run the actual
command registration and argument parsing.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

_ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def _plain_text(output: str) -> str:
    """The message as words: no colors, no panel frame, no line wrapping."""
    return ' '.join(_ANSI.sub('', output).replace('│', ' ').split())


@pytest.mark.parametrize(
    'args',
    [
        [],
        ['--help'],
        ['download', '--help'],
        ['check', '--help'],
        ['clean-cache', '--help'],
        ['show-auth-script', '--help'],
    ],
    ids=['no-args', 'help', 'download', 'check', 'clean-cache', 'show-auth-script'],
)
def test_help_screens_exit_cleanly(args: list[str]) -> None:
    """A broken command registration would crash before doing any work."""
    result = runner.invoke(typer_app, args)

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize('command', ['download', 'check', 'clean-cache'])
def test_command_without_username_is_a_usage_error(command: str) -> None:
    """Regression for 5.1: a missing creator name used to crash instead of a hint."""
    result = runner.invoke(typer_app, [command])

    assert result.exit_code == 2
    assert 'USERNAME' in result.output


def test_the_old_username_flag_is_gone() -> None:
    """The flag was replaced by the positional argument; typer must reject it."""
    result = runner.invoke(typer_app, ['check', '-u', 'someone'])

    assert result.exit_code == 2
    assert 'No such option' in result.output


@pytest.mark.parametrize(
    ('url', 'expected'),
    [
        ('https://boosty.to/someone', 'not a Boosty post link'),
        ('https://boosty.to/other/posts/a2dd6942', "belongs to 'other'"),
    ],
    ids=['not-a-post-link', 'another-creator'],
)
def test_post_url_is_checked_before_anything_runs(url: str, expected: str) -> None:
    """Bug: a post of creator B was saved and cached under creator A's name."""
    result = runner.invoke(typer_app, ['download', 'someone', '--post-url', url])

    assert result.exit_code == 2
    assert expected in _plain_text(result.output)


VALID_CONFIG = 'auth:\n  cookie: "session=x"\n  auth_header: "Bearer x"\n'
BROKEN_CONFIG = 'auth: [1, 2, 3]\n'


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return path


def test_clean_cache_runs_without_an_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The only sync command: settings loading must not need asyncio to be running."""
    monkeypatch.chdir(tmp_path)
    _write(tmp_path / 'config.yaml', VALID_CONFIG)

    result = runner.invoke(
        typer_app, ['clean-cache', 'someone', '--cache-dir', str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert 'nothing to clean' in _plain_text(result.output)


def test_config_flag_points_at_a_file_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before, the config could only be config.yaml in the working directory."""
    monkeypatch.chdir(tmp_path)
    config = _write(tmp_path / 'elsewhere' / 'main.yaml', VALID_CONFIG)

    result = runner.invoke(
        typer_app,
        [
            '--config',
            str(config),
            'clean-cache',
            'someone',
            '--cache-dir',
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0, result.output
    assert 'nothing to clean' in _plain_text(result.output)
    assert not (tmp_path / 'config.yaml').exists(), 'no sample next to the cwd'


def test_config_env_var_works_like_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _write(tmp_path / 'elsewhere' / 'main.yaml', VALID_CONFIG)

    result = runner.invoke(
        typer_app,
        ['clean-cache', 'someone', '--cache-dir', str(tmp_path)],
        env={'BOOSTY_DOWNLOADER_CONFIG': str(config)},
    )

    assert result.exit_code == 0, result.output


def test_config_flag_wins_over_the_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-off --config must not be overridden by a variable set in the shell."""
    monkeypatch.chdir(tmp_path)
    broken = _write(tmp_path / 'broken.yaml', BROKEN_CONFIG)
    valid = _write(tmp_path / 'valid.yaml', VALID_CONFIG)

    result = runner.invoke(
        typer_app,
        [
            '--config',
            str(valid),
            'clean-cache',
            'someone',
            '--cache-dir',
            str(tmp_path),
        ],
        env={'BOOSTY_DOWNLOADER_CONFIG': str(broken)},
    )

    assert result.exit_code == 0, result.output


def test_missing_config_at_the_flag_path_gets_a_sample_there(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """First run with --config: the sample lands where the user pointed, not in the cwd."""
    monkeypatch.chdir(tmp_path)
    config = tmp_path / 'boosty' / 'main.yaml'
    config.parent.mkdir()

    result = runner.invoke(
        typer_app, ['--config', str(config), 'clean-cache', 'someone']
    )

    assert result.exit_code == 1
    assert config.exists()
    assert 'Created a sample config file' in _plain_text(result.output)
    assert not (tmp_path / 'config.yaml').exists()


def test_root_help_names_the_env_var() -> None:
    result = runner.invoke(typer_app, ['--help'])

    assert '--config' in result.output
    assert 'BOOSTY_DOWNLOADER_CONFIG' in _plain_text(result.output)
