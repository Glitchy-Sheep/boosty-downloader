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


def test_download_without_username_is_a_usage_error() -> None:
    """Regression for 5.1: a missing --username used to crash instead of a hint."""
    result = runner.invoke(typer_app, ['download'])

    assert result.exit_code == 2
    assert 'username' in result.output
