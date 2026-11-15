"""CLI smoke: the real typer app parses argv - a net for command wiring.

Unlike exit_codes_test.py (which stubs the app), these run the actual
command registration and argument parsing.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from boosty_downloader.cli.commands import download as download_command
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
        ['reindex', '--help'],
        ['render', '--help'],
        ['show-auth-script', '--help'],
    ],
    ids=[
        'no-args',
        'help',
        'download',
        'check',
        'reindex',
        'render',
        'show-auth-script',
    ],
)
def test_help_screens_exit_cleanly(args: list[str]) -> None:
    """A broken command registration would crash before doing any work."""
    result = runner.invoke(typer_app, args)

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize('command', ['download', 'check'])
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


# Broken for every reader of the file, the credentials-free one included.
BROKEN_CONFIG = 'downloading_settings: [1, 2, 3]\n'


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    return path


def _config_naming_the_library(path: Path, root: Path, cache: Path) -> Path:
    """Path-only configuration used by the offline index command."""
    return _write(
        path,
        json.dumps(
            {
                'downloading_settings': {
                    'target_directory': str(root),
                    'cache_directory': str(cache),
                },
            }
        ),
    )


def test_clean_cache_is_unknown_and_keeps_older_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    legacy = tmp_path / 'cache' / 'someone' / 'post_cache.db'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'older download state')
    before = legacy.stat().st_mtime_ns

    result = runner.invoke(
        typer_app,
        ['clean-cache', 'someone', '--cache-dir', str(tmp_path / 'cache'), '--yes'],
    )

    assert result.exit_code == 2
    assert 'No such command' in _plain_text(result.output)
    assert legacy.read_bytes() == b'older download state'
    assert legacy.stat().st_mtime_ns == before
    assert not (tmp_path / 'config.yaml').exists()
    help_text = _plain_text(runner.invoke(typer_app, ['--help']).output)
    assert 'clean-cache' not in help_text
    assert 'reindex' in help_text


def test_config_flag_points_at_a_file_anywhere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / 'cache'
    config = _config_naming_the_library(
        tmp_path / 'elsewhere' / 'main.yaml', tmp_path / 'library', cache
    )

    result = runner.invoke(typer_app, ['--config', str(config), 'reindex'])

    assert result.exit_code == 0, result.output
    assert (cache / 'index.db').is_file()
    assert not (tmp_path / 'boosty-downloads').exists()
    assert not (tmp_path / 'config.yaml').exists()


def test_config_env_var_works_like_the_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    cache = tmp_path / 'cache'
    config = _config_naming_the_library(
        tmp_path / 'elsewhere' / 'main.yaml', tmp_path / 'library', cache
    )

    result = runner.invoke(
        typer_app, ['reindex'], env={'BOOSTY_DOWNLOADER_CONFIG': str(config)}
    )

    assert result.exit_code == 0, result.output
    assert (cache / 'index.db').is_file()
    assert not (tmp_path / 'boosty-downloads').exists()
    assert not (tmp_path / 'config.yaml').exists()


def test_config_flag_wins_over_the_env_var(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    broken = _write(tmp_path / 'broken.yaml', BROKEN_CONFIG)
    cache = tmp_path / 'selected-cache'
    valid = _config_naming_the_library(
        tmp_path / 'valid.yaml', tmp_path / 'library', cache
    )

    result = runner.invoke(
        typer_app,
        ['--config', str(valid), 'reindex'],
        env={'BOOSTY_DOWNLOADER_CONFIG': str(broken)},
    )

    assert result.exit_code == 0, result.output
    assert (cache / 'index.db').is_file()
    assert not (tmp_path / 'boosty-downloads').exists()


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


@pytest.mark.parametrize(
    'extra',
    [[], ['--dry-run'], ['--post-url', 'https://boosty.to/someone/posts/p1']],
)
def test_exclude_tag_options_reach_the_download_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra: list[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    calls: list[object] = []

    async def record_download(**kwargs: object) -> None:
        calls.append(kwargs['excluded_tags'])

    monkeypatch.setattr(download_command, '_download_handler', record_download)
    result = runner.invoke(
        typer_app,
        [
            'download',
            'someone',
            '--exclude-tag',
            ' SAMPLE ',
            '--exclude-tag',
            'sample tag',
            *extra,
        ],
    )

    assert result.exit_code == 0, result.output
    assert calls == [('SAMPLE', 'sample tag')]


@pytest.mark.parametrize('tag', ['', '   '])
def test_empty_excluded_tag_is_a_usage_error(tag: str) -> None:
    result = runner.invoke(typer_app, ['download', 'someone', '--exclude-tag', tag])
    assert result.exit_code == 2
    assert 'tag must not be empty' in _plain_text(result.output)


def test_download_help_explains_restore_missing() -> None:
    result = runner.invoke(typer_app, ['download', '--help'])
    help_text = _plain_text(result.output)

    assert result.exit_code == 0
    assert '--restore-missing' in help_text
    assert (
        'Download selected media deleted locally if it is still present in the post'
        in help_text
    )
