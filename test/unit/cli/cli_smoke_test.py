"""CLI smoke: the real typer app parses argv - a net for command wiring.

Unlike exit_codes_test.py (which stubs the app), these run the actual
command registration and argument parsing.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from boosty_downloader.infrastructure.post_caching.post_cache import SQLitePostCache
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
# Broken for every reader of the file, the credentials-free one included.
BROKEN_CONFIG = 'downloading_settings: [1, 2, 3]\n'


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return path


def _plant_cache(cache_root: Path, username: str) -> Path:
    """A creator's cache database, as a download run leaves it."""
    db = cache_root / username / SQLitePostCache.DEFAULT_CACHE_FILENAME
    db.parent.mkdir(parents=True, exist_ok=True)
    db.write_bytes(b'')
    return db


def _config_naming_the_cache(path: Path, cache_root: Path) -> Path:
    """A config that only says where the cache is; no credentials in it."""
    return _write(
        path, f'downloading_settings:\n  cache_directory: "{cache_root.as_posix()}"\n'
    )


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


def test_clean_cache_asks_first_and_a_no_keeps_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache is the only record of what was downloaded; it used to go without a question."""
    monkeypatch.chdir(tmp_path)
    db = _plant_cache(tmp_path / 'cache', 'someone')

    result = runner.invoke(
        typer_app,
        ['clean-cache', 'someone', '--cache-dir', str(tmp_path / 'cache')],
        input='n\n',
    )

    assert result.exit_code == 0, result.output
    assert 'the next run downloads everything again' in _plain_text(result.output)
    assert db.exists()
    assert 'is kept' in _plain_text(result.output)


def test_clean_cache_yes_skips_the_question(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    db = _plant_cache(tmp_path / 'cache', 'someone')

    result = runner.invoke(
        typer_app,
        ['clean-cache', 'someone', '--cache-dir', str(tmp_path / 'cache'), '--yes'],
    )

    assert result.exit_code == 0, result.output
    assert 'Continue?' not in result.output
    assert not db.exists()
    assert 'cleaned successfully' in _plain_text(result.output)


def test_clean_cache_needs_no_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing a local file must not require a valid token: the folders are enough."""
    monkeypatch.chdir(tmp_path)
    _config_naming_the_cache(tmp_path / 'config.yaml', tmp_path / 'cache')
    db = _plant_cache(tmp_path / 'cache', 'someone')

    result = runner.invoke(typer_app, ['clean-cache', 'someone', '--yes'])

    assert result.exit_code == 0, result.output
    assert not db.exists(), 'the cache folder named in the config must be found'


def test_clean_cache_without_any_config_leaves_no_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(
        typer_app, ['clean-cache', 'someone', '--cache-dir', str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    assert 'nothing to clean' in _plain_text(result.output)
    assert not (tmp_path / 'config.yaml').exists()


def test_config_flag_points_at_a_file_anywhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Before, the config could only be config.yaml in the working directory."""
    monkeypatch.chdir(tmp_path)
    config = _config_naming_the_cache(
        tmp_path / 'elsewhere' / 'main.yaml', tmp_path / 'cache'
    )
    db = _plant_cache(tmp_path / 'cache', 'someone')

    result = runner.invoke(
        typer_app, ['--config', str(config), 'clean-cache', 'someone', '--yes']
    )

    assert result.exit_code == 0, result.output
    assert not db.exists(), 'the cache folder comes from the file named by --config'
    assert not (tmp_path / 'config.yaml').exists(), 'no sample next to the cwd'


def test_config_env_var_works_like_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    config = _config_naming_the_cache(
        tmp_path / 'elsewhere' / 'main.yaml', tmp_path / 'cache'
    )
    db = _plant_cache(tmp_path / 'cache', 'someone')

    result = runner.invoke(
        typer_app,
        ['clean-cache', 'someone', '--yes'],
        env={'BOOSTY_DOWNLOADER_CONFIG': str(config)},
    )

    assert result.exit_code == 0, result.output
    assert not db.exists()


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

    result = runner.invoke(typer_app, ['--config', str(config), 'check', 'someone'])

    assert result.exit_code == 1
    assert config.exists()
    assert 'Created a sample config file' in _plain_text(result.output)
    assert not (tmp_path / 'config.yaml').exists()


def test_root_help_names_the_env_var() -> None:
    """In CI rich colors the option name, so the raw output splits it with ANSI codes."""
    help_text = _plain_text(runner.invoke(typer_app, ['--help']).output)

    assert '--config' in help_text
    assert 'BOOSTY_DOWNLOADER_CONFIG' in help_text
