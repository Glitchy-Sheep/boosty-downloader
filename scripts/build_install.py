"""Build wheel and install it locally for testing."""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console

DIST_DIR = Path('dist')
PYPROJECT = Path('pyproject.toml')

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
console = Console(force_terminal=True)


def _get_version() -> str:
    text = PYPROJECT.read_text(encoding='utf-8')
    m = re.search(r'version = "([^"]*)"', text)
    return m.group(1) if m else '?'


def main() -> None:
    """Clean dist/, build a fresh wheel, install it with pip."""
    version = _get_version()

    console.print()
    console.print(f'  :package: [bold]boosty-downloader[/] [cyan]v{version}[/]')
    console.print()

    # --- Step 1: Clean dist/ -------------------------------------------------
    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    console.print('  [dim]1.[/] Cleaned dist/')

    # --- Step 2: Build -------------------------------------------------------
    console.print('  [dim]2.[/] Building wheel...')
    subprocess.run(
        ['uv', 'build'],
        check=True,
    )

    wheels = list(DIST_DIR.glob('*.whl'))
    if not wheels:
        console.print('  [red bold]Error:[/] no .whl found in dist/')
        sys.exit(1)

    wheel = wheels[0]
    console.print(f'     [green]{wheel.name}[/]')

    # --- Step 3: Install globally via pipx ------------------------------------
    # pipx puts the wheel into its own isolated env with the CLI on PATH -
    # the same end-user layout on macOS / Linux / Windows. A bare
    # `pip install --user` breaks on Homebrew/system pythons (PEP 668).
    pipx = shutil.which('pipx')
    if pipx is None:
        console.print(
            '  [red bold]Error:[/] pipx is required to install the wheel globally.'
        )
        console.print(
            '  Install it: [cyan]brew install pipx[/] (macOS) / '
            '[cyan]scoop install pipx[/] (Windows) / '
            '[cyan]python3 -m pip install --user pipx[/]'
        )
        sys.exit(1)

    console.print('  [dim]3.[/] Installing globally via [cyan]pipx[/]...')
    subprocess.run(
        [pipx, 'install', '--force', str(wheel)],
        check=True,
    )

    # --- Done ----------------------------------------------------------------
    console.print()
    console.print(f'  :white_check_mark: [green bold]Installed v{version} globally[/]')
    console.print()
    console.print('  [dim]Test it:[/]')
    console.print('  [cyan]boosty-downloader --help[/]')
    console.print()


if __name__ == '__main__':
    main()
