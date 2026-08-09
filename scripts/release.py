"""Bump version in pyproject.toml and promote Unreleased changelog entries."""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path
from typing import NoReturn

from rich.console import Console

PYPROJECT = Path('pyproject.toml')
CHANGELOG = Path('CHANGELOG.md')
UNRELEASED_HEADING = '## Unreleased'
BUMP_KEYWORDS = ('major', 'minor', 'patch')

# Wrap stdout in UTF-8 so emojis work on Windows legacy consoles (cp1252/cp866).
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
console = Console(force_terminal=True)


def _error(msg: str) -> NoReturn:
    console.print(f'  [red bold]Error:[/] {msg}')
    sys.exit(1)


def _parse_semver(text: str) -> tuple[int, int, int]:
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', text)
    if not m:
        _error(f'could not find semver in: {text}')
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _current_version() -> tuple[int, int, int]:
    pyproject_text = PYPROJECT.read_text(encoding='utf-8')
    m = re.search(r'version = "(\d+\.\d+\.\d+)"', pyproject_text)
    if not m:
        _error(f'could not find version in {PYPROJECT}')
    return _parse_semver(m.group(1))


def _bump(current: tuple[int, int, int], part: str) -> str:
    major, minor, patch = current
    if part == 'major':
        return f'{major + 1}.0.0'
    if part == 'minor':
        return f'{major}.{minor + 1}.0'
    return f'{major}.{minor}.{patch + 1}'


def _resolve_version(arg: str) -> str:
    """Turn 'patch', 'minor', 'major' or an explicit X.Y.Z into a version string."""
    if arg in BUMP_KEYWORDS:
        current = _current_version()
        version = _bump(current, arg)
        current_str = '.'.join(map(str, current))
        console.print(f'  [dim]{current_str}[/] -> [bold]{version}[/] [dim]({arg})[/]')
        return version

    if not re.fullmatch(r'\d+\.\d+\.\d+', arg):
        _error(f'expected major/minor/patch or X.Y.Z, got "{arg}"')

    return arg


def main() -> None:
    """Validate inputs, bump version and update changelog."""
    if len(sys.argv) != 2 or not sys.argv[1]:  # noqa: PLR2004
        console.print(
            '  [yellow]Usage:[/] python scripts/release.py [major|minor|patch|X.Y.Z]'
        )
        sys.exit(1)

    version = _resolve_version(sys.argv[1])

    # --- Validate ---------------------------------------------------------
    current = _current_version()
    new = _parse_semver(version)
    if new <= current:
        current_str = '.'.join(map(str, current))
        _error(f'new version {version} must be higher than current {current_str}')

    changelog_text = CHANGELOG.read_text(encoding='utf-8')

    if f'## {version}' in changelog_text:
        _error(f'version {version} already exists in {CHANGELOG}')

    if UNRELEASED_HEADING not in changelog_text:
        _error(f'"{UNRELEASED_HEADING}" section not found in {CHANGELOG}')

    # Extract content between ## Unreleased and the next ## heading
    after_unreleased = changelog_text.split('## Unreleased\n', 1)
    if len(after_unreleased) > 1:
        rest = after_unreleased[1]
        next_heading = re.search(r'^## ', rest, re.MULTILINE)
        entries = (rest[: next_heading.start()] if next_heading else rest).strip()
    else:
        entries = ''
    if not entries:
        _error(f'"{UNRELEASED_HEADING}" section is empty - nothing to release')

    # --- Apply changes ----------------------------------------------------
    pyproject_text = PYPROJECT.read_text(encoding='utf-8')
    pyproject_text = re.sub(
        r'version = "[^"]*"',
        f'version = "{version}"',
        pyproject_text,
        count=1,
    )
    PYPROJECT.write_text(pyproject_text, encoding='utf-8')

    changelog_text = changelog_text.replace(
        f'{UNRELEASED_HEADING}\n',
        f'{UNRELEASED_HEADING}\n\n## {version}\n',
        1,
    )
    CHANGELOG.write_text(changelog_text, encoding='utf-8')

    # --- Report -----------------------------------------------------------
    console.print()
    console.print(f'  :rocket: [green bold]v{version}[/]')
    console.print()
    for line in entries.splitlines():
        console.print(f'  {line}')
    console.print()
    console.print('  :point_right: [yellow bold]Next steps[/]')
    console.print()
    console.print('  [dim]1.[/] git diff')
    console.print('  [dim]2.[/] git add pyproject.toml CHANGELOG.md')
    console.print(f'  [dim]3.[/] git commit -m [cyan]"chore: release v{version}"[/]')
    console.print('  [dim]4.[/] push the branch, open a PR, merge it')
    console.print('  [dim]5.[/] git checkout main && git pull')
    console.print(
        f'  [dim]6.[/] git tag [cyan]v{version}[/] && git push origin [cyan]v{version}[/]'
    )
    console.print('  [dim]See docs/development/04-releasing.md for details[/]')
    console.print()


if __name__ == '__main__':
    main()
