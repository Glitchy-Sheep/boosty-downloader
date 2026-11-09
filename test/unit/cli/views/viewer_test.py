"""Viewer console messages preserve literal paths and runnable examples."""

from pathlib import Path
from shlex import split
from types import SimpleNamespace

import pytest
from rich.text import Text

from boosty_downloader.cli.views import viewer
from boosty_downloader.viewer.server import ServerAddresses


@pytest.mark.parametrize(
    'name', ['library with spaces', "owner's & $(example) library"]
)
def test_empty_library_command_quotes_the_posix_destination(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(name)
    monkeypatch.setattr(viewer, 'os', SimpleNamespace(name='posix'))

    message = viewer.empty_library_message(root)
    command = message.splitlines()[-1]

    assert 'No library yet' in message
    assert split(command) == [
        'boosty-downloader',
        'download',
        'AUTHOR',
        '-o',
        str(root),
    ]


def test_empty_library_command_quotes_powershell_apostrophes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path("C:\\Files & more\\owner's library")
    monkeypatch.setattr(viewer, 'os', SimpleNamespace(name='nt'))

    message = viewer.empty_library_message(root)

    assert (
        message.splitlines()[-1]
        == "boosty-downloader download AUTHOR -o 'C:\\Files & more\\owner''s library'"
    )


def test_startup_uses_actual_local_and_lan_addresses() -> None:
    addresses = ServerAddresses(
        9321, ('http://192.0.2.7:9321/', 'http://my-machine.local:9321/')
    )

    message = Text.from_markup(viewer.render_viewer_started(addresses)).plain

    assert message.splitlines() == [
        'Viewer: http://127.0.0.1:9321/',
        'Home network: http://192.0.2.7:9321/',
        'Home network: http://my-machine.local:9321/',
        'Press Ctrl+C to stop.',
    ]


def test_failure_message_keeps_rich_markup_literal() -> None:
    reason = '[bold]library[red] is unavailable[/bold]'

    message = Text.from_markup(viewer.render_viewer_failure(reason)).plain

    assert message == f'Cannot open the library viewer: {reason}'
