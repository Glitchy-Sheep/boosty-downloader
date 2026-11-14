"""Console messages for starting the local library viewer."""

from __future__ import annotations

import os
from shlex import quote
from typing import TYPE_CHECKING

from rich.markup import escape

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.viewer.server import ServerAddresses


def _command_path(root: Path) -> str:
    if os.name == 'nt':
        return "'" + str(root).replace("'", "''") + "'"
    return quote(str(root))


def empty_library_message(root: Path) -> str:
    """Explain how to create a library, with a shell-quoted destination."""
    command = f'boosty-downloader download AUTHOR -o {_command_path(root)}'
    return f'No library yet in {root}. Download posts first:\n{command}'


def render_viewer_started(addresses: ServerAddresses) -> str:
    """Show only addresses that belong to the listener that actually started."""
    lines = [f'Viewer: [bold]{escape(addresses.local)}[/bold]']
    lines.extend(f'Home network: {escape(url)}' for url in addresses.network)
    lines.append('Press Ctrl+C to stop.')
    return '\n'.join(lines)


def render_viewer_failure(reason: str) -> str:
    """Keep folder names and diagnostics literal in Rich output."""
    return f'Cannot open the library viewer: {escape(reason)}'


def render_opener_recording(path: str) -> str:
    """Make the explicit recording hook visible before any file action."""
    return f'File actions are recorded to {escape(path)}; no files are opened.'
