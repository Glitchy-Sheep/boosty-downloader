"""CLI smoke: the real typer app parses argv - a net for command wiring.

Unlike exit_codes_test.py (which stubs the app), these run the actual
command registration and argument parsing.
"""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from boosty_downloader.main import typer_app

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
