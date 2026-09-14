"""CLI smoke: the real typer app parses argv - a net for command wiring.

Unlike exit_codes_test.py (which stubs the app), these run the actual
command registration and argument parsing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


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
    # rich wraps the message inside a bordered panel; read it without the frame.
    assert expected in ' '.join(result.output.replace('│', ' ').split())


def test_clean_cache_runs_without_an_event_loop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The only sync command: settings loading must not need asyncio to be running."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'config.yaml').write_text(
        'auth:\n  cookie: "session=x"\n  auth_header: "Bearer x"\n',
        encoding='utf-8',
    )

    result = runner.invoke(
        typer_app, ['clean-cache', 'someone', '--cache-dir', str(tmp_path)]
    )

    assert result.exit_code == 0, result.output
    # rich wraps log lines at the terminal width; compare without the wrapping.
    assert 'nothing to clean' in ' '.join(result.output.split())
