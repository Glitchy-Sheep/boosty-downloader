"""CLI command: show JavaScript helper for extracting Boosty credentials."""

# pyright: reportUnusedFunction=false
from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.src.cli.boosty_token_viewer import (
    show_js_helper_script,
)

if TYPE_CHECKING:
    import typer


def register(app: typer.Typer) -> None:
    """Register the show-auth-script command."""

    @app.command('show-auth-script')
    def show_auth_script_entrypoint() -> None:
        """Show a JS helper script to extract Boosty credentials from browser console."""
        show_js_helper_script()
