"""Interactive release wizard: preflight checks, preview, release PR, tag."""

from __future__ import annotations

import io
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, NoReturn, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Sequence

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.prompt import Confirm

Command: TypeAlias = tuple[str, ...]

PYPROJECT = Path('pyproject.toml')
CHANGELOG = Path('CHANGELOG.md')
UNRELEASED_HEADING = '## Unreleased'
BUMP_KEYWORDS = ('major', 'minor', 'patch')
PYPI_PROJECT = 'boosty-downloader'
HTTP_NOT_FOUND = 404
ACTIONS_URL = (
    'https://github.com/Glitchy-Sheep/boosty-downloader/actions/workflows/release.yaml'
)

# Wrap stdout in UTF-8 so emojis work on Windows legacy consoles (cp1252/cp866).
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
console = Console(force_terminal=True)


# --- Console and subprocess helpers ------------------------------------------


def _error(msg: str) -> NoReturn:
    console.print(f'  [red bold]Error:[/] {msg}')
    sys.exit(1)


def _ok(msg: str) -> None:
    console.print(f'  [green]✅[/] {msg}')


def _warn(msg: str) -> None:
    console.print(f'  [yellow]⚠️[/] {msg}')


def _abort(msg: str) -> NoReturn:
    console.print(f'  [yellow]{msg}[/]')
    sys.exit(0)


def _run(*cmd: str, echo: bool = False) -> str:
    """Run a command that must succeed; a failure stops the wizard."""
    if echo:
        console.print(f'  [dim]$ {escape(shlex.join(cmd))}[/]')
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        _error(f'`{shlex.join(cmd)}` failed:\n{result.stderr.strip()}')
    return result.stdout.strip()


def _try(*cmd: str) -> tuple[int, str]:
    """Run a command whose failure is an expected outcome, not an error."""
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return result.returncode, result.stdout.strip()


def _render_commands(commands: Sequence[Command], indent: str) -> list[str]:
    """Render a command ladder: ├─ for every command, └─ for the last one."""
    if not commands:
        return []
    joints = ['├─'] * (len(commands) - 1) + ['└─']
    return [
        f'{indent}[dim]{joint} {escape(shlex.join(cmd))}[/]'
        for joint, cmd in zip(joints, commands, strict=True)
    ]


# --- Version helpers ---------------------------------------------------------


def _parse_semver(text: str) -> tuple[int, int, int]:
    m = re.search(r'(\d+)\.(\d+)\.(\d+)', text)
    if not m:
        _error(f'could not find semver in: {text}')
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _current_version() -> str:
    m = re.search(r'version = "(\d+\.\d+\.\d+)"', PYPROJECT.read_text(encoding='utf-8'))
    if not m:
        _error(f'could not find version in {PYPROJECT}')
    return m.group(1)


def _bumped(current: str, part: str) -> str:
    major, minor, patch = _parse_semver(current)
    if part == 'major':
        return f'{major + 1}.0.0'
    if part == 'minor':
        return f'{major}.{minor + 1}.0'
    return f'{major}.{minor}.{patch + 1}'


def _resolve_version(arg: str) -> str:
    """Turn 'patch', 'minor', 'major' or an explicit X.Y.Z into a version string."""
    if arg in BUMP_KEYWORDS:
        return _bumped(_current_version(), arg)
    if not re.fullmatch(r'\d+\.\d+\.\d+', arg):
        _error(f'expected major/minor/patch or X.Y.Z, got "{arg}"')
    return arg


def _notes_summary(entries: str) -> str:
    """Compress the release notes into one line: '7 entries: 1 added, 5 fixed'."""
    counts: dict[str, int] = {}
    section = ''
    total = 0
    for line in entries.splitlines():
        if line.startswith('### '):
            section = line[4:].strip().lower()
        elif line.startswith('- '):
            total += 1
            if section:
                counts[section] = counts.get(section, 0) + 1
    if not counts:
        return f'{total} entries'
    parts = ', '.join(f'{n} {name}' for name, n in counts.items())
    return f'{total} entries: {parts}'


# --- Release plan ------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReleasePlan:
    """Single source of truth: the preview and the execution both read from here."""

    old_version: str
    version: str
    entries: str
    needs_branch: bool

    @property
    def branch(self) -> str:
        return f'release/v{self.version}'

    @property
    def commit_message(self) -> str:
        return f'chore: release v{self.version}'

    @property
    def branch_command(self) -> Command | None:
        return ('git', 'switch', '-c', self.branch) if self.needs_branch else None

    @property
    def commit_commands(self) -> tuple[Command, ...]:
        return (
            ('git', 'add', 'pyproject.toml', 'CHANGELOG.md', 'uv.lock'),
            ('git', 'commit', '-m', self.commit_message),
            ('git', 'push', '-u', 'origin', self.branch),
        )

    @property
    def pr_command(self) -> Command:
        return (
            'gh', 'pr', 'create',
            '--base', 'main',
            '--title', self.commit_message,
            '--assignee', '@me',
            '--label', 'ci/skip-changelog',
        )  # fmt: skip


# --- Preflight checks --------------------------------------------------------


def _check_tools() -> None:
    """Verify git and gh are installed and gh is logged in - the wizard drives both."""
    missing = [tool for tool in ('git', 'gh') if shutil.which(tool) is None]
    if missing:
        _error(f'required tools not found: {", ".join(missing)}')
    code, _ = _try('gh', 'auth', 'status')
    if code != 0:
        _error('gh is not authorized - run: gh auth login')
    _ok('git and gh are ready, gh is authorized')


def _check_tree_clean() -> None:
    """Require a clean tree; only CHANGELOG.md edits ride in the release commit."""
    lines = _run('git', 'status', '--porcelain', '-uno').splitlines()
    dirty = [line for line in lines if not line.endswith('CHANGELOG.md')]
    if dirty:
        files = '\n'.join(f'    {line}' for line in dirty)
        _error(f'uncommitted changes - commit or stash them first:\n{files}')
    if lines:
        _ok('tree clean (CHANGELOG.md edits will ride in the release commit)')
    else:
        _ok('working tree clean')


def _check_branch(branch: str) -> bool:
    """
    Ensure the start point: a fresh main or the existing release branch.

    Returns True when the release branch still needs to be created.
    """
    current = _run('git', 'rev-parse', '--abbrev-ref', 'HEAD')
    _run('git', 'fetch', 'origin', 'main', '--tags')
    if current == branch:
        behind = _run('git', 'rev-list', '--count', 'HEAD..origin/main')
        if behind != '0':
            _warn(f'origin/main is {behind} commit(s) ahead - consider merging it in')
        _ok(f'already on {branch} - continuing here')
        return False
    if current != 'main':
        _error(f'start from main (or {branch}), current branch is {current}')
    _run('git', 'pull', '--ff-only', 'origin', 'main')
    _ok('on main, fast-forwarded to origin/main')
    return True


def _extract_unreleased(changelog_text: str) -> str:
    if UNRELEASED_HEADING not in changelog_text:
        _error(f'"{UNRELEASED_HEADING}" section not found in {CHANGELOG}')
    rest = changelog_text.split(f'{UNRELEASED_HEADING}\n', 1)[1]
    next_heading = re.search(r'^## ', rest, re.MULTILINE)
    return (rest[: next_heading.start()] if next_heading else rest).strip()


def _check_changelog(version: str) -> str:
    """Require content in Unreleased - it becomes the release notes."""
    text = CHANGELOG.read_text(encoding='utf-8')
    if f'## {version}' in text:
        _error(f'version {version} already exists in {CHANGELOG}')
    entries = _extract_unreleased(text)
    if not entries:
        _error(f'"{UNRELEASED_HEADING}" section is empty - nothing to release')
    _ok(f'changelog: {_notes_summary(entries)}')
    return entries


def _check_pypi_free(version: str) -> None:
    """Refuse to reuse a version number: a published release cannot be replaced."""
    url = f'https://pypi.org/pypi/{PYPI_PROJECT}/{version}/json'
    # For this check 404 is the good outcome: the version is not on PyPI yet.
    try:
        urllib.request.urlopen(url, timeout=15)  # noqa: S310 - fixed https host
    except urllib.error.HTTPError as err:
        if err.code != HTTP_NOT_FOUND:
            _error(f'PyPI answered {err.code} for {url}')
        _ok(f'{version} is free on PyPI')
    except urllib.error.URLError as err:
        _error(f'could not reach PyPI: {err.reason}')
    else:
        _error(f'{version} already exists on PyPI')


def _check_tag_free(tag: str) -> None:
    """Require the tag to be absent everywhere - the tag is the publish trigger."""
    if _run('git', 'tag', '--list', tag):
        _error(f'tag {tag} already exists locally')
    if _run('git', 'ls-remote', '--tags', 'origin', f'refs/tags/{tag}'):
        _error(f'tag {tag} already exists on origin')
    _ok(f'tag {tag} is free')


# --- Release flow ------------------------------------------------------------


def _build_plan(arg: str) -> ReleasePlan:
    """Run every preflight check and return the plan they agree on."""
    old = _current_version()
    version = _resolve_version(arg)
    if _parse_semver(version) <= _parse_semver(old):
        _error(f'new version {version} must be higher than current {old}')

    console.print()
    console.print(f'  [bold]🔍 Preflight for v{version}[/]')
    _check_tools()
    _check_tree_clean()
    needs_branch = _check_branch(f'release/v{version}')
    entries = _check_changelog(version)
    _check_pypi_free(version)
    _check_tag_free(f'v{version}')
    return ReleasePlan(
        old_version=old, version=version, entries=entries, needs_branch=needs_branch
    )


def _plan_steps(plan: ReleasePlan) -> list[tuple[str, tuple[Command, ...]]]:
    steps: list[tuple[str, tuple[Command, ...]]] = []
    if plan.branch_command:
        steps.append(
            (f'create [cyan]{plan.branch}[/] from main', (plan.branch_command,))
        )
    steps += [
        (f'bump [dim]{plan.old_version}[/] -> [bold]{plan.version}[/]'
         ' in pyproject.toml and uv.lock', ()),
        (f'promote "{UNRELEASED_HEADING}" -> "## {plan.version}" in CHANGELOG.md', ()),
        ('commit and push', plan.commit_commands),
        ('open the release PR', (plan.pr_command,)),
    ]  # fmt: skip
    return steps


def _confirm_release(plan: ReleasePlan) -> None:
    lines: list[str] = []
    if not plan.needs_branch:
        lines.append(
            f'Already on [cyan]{plan.branch}[/] - releasing from this branch.\n'
        )
    for number, (title, commands) in enumerate(_plan_steps(plan), 1):
        lines.append(f'{number}. {title}')
        lines.extend(_render_commands(commands, '   '))
    footer = (
        f'[dim]Release notes ({_notes_summary(plan.entries)}) '
        'go to the PR body and the GitHub Release.[/]'
    )
    console.print()
    console.print(
        Panel(
            '\n'.join(lines) + f'\n\n{footer}',
            title=f'Release v{plan.version}',
            border_style='cyan',
        )
    )
    if not Confirm.ask('  Proceed?', default=False):
        _abort('Aborted - nothing changed.')


def _apply_bump(version: str) -> None:
    pyproject_text = re.sub(
        r'version = "[^"]*"',
        f'version = "{version}"',
        PYPROJECT.read_text(encoding='utf-8'),
        count=1,
    )
    PYPROJECT.write_text(pyproject_text, encoding='utf-8')

    changelog_text = CHANGELOG.read_text(encoding='utf-8').replace(
        f'{UNRELEASED_HEADING}\n', f'{UNRELEASED_HEADING}\n\n## {version}\n', 1
    )
    CHANGELOG.write_text(changelog_text, encoding='utf-8')

    # uv.lock records the project's own version - it must move together
    # with pyproject.toml, or the next `uv run` dirties the tree.
    _run('uv', 'lock')
    _ok(f'pyproject.toml, CHANGELOG.md and uv.lock updated for {version}')


def _commit_and_push(plan: ReleasePlan) -> None:
    if plan.branch_command:
        _run(*plan.branch_command, echo=True)
    for cmd in plan.commit_commands:
        _run(*cmd, echo=True)
    _ok(f'pushed {plan.branch}')


def _pr_body(plan: ReleasePlan) -> str:
    return (
        f'Promotes the Unreleased changelog into v{plan.version} '
        'and bumps the version.\n\n'
        f'## Release notes\n\n{plan.entries}\n\n'
        '## After merge\n\n'
        'Run `task release:tag` - it verifies fresh main and pushes the tag; '
        'the tag triggers the release workflow (build -> PyPI -> GitHub Release).\n'
    )


def _open_pr(plan: ReleasePlan) -> None:
    code, url = _try('gh', 'pr', 'view', '--json', 'url', '--jq', '.url')
    if code == 0 and url:
        _ok(f'release PR already exists: {url}')
        return
    with tempfile.NamedTemporaryFile(
        'w', suffix='.md', delete=False, encoding='utf-8'
    ) as body:
        body.write(_pr_body(plan))
        body_path = body.name
    url = _run(*plan.pr_command, '--body-file', body_path, echo=True)
    Path(body_path).unlink(missing_ok=True)
    _ok(f'release PR opened: {url}')


def _release_flow(arg: str) -> None:
    plan = _build_plan(arg)
    _confirm_release(plan)

    console.print()
    console.print('  [bold]🚀 Executing[/]')
    _apply_bump(plan.version)
    _commit_and_push(plan)
    _open_pr(plan)
    console.print()
    console.print(
        Panel(
            'Merge the PR, then run [cyan]task release:tag[/] '
            f'to publish v{plan.version}.',
            title='Next',
            border_style='green',
        )
    )


# --- Tag flow ----------------------------------------------------------------


def _check_main_ready() -> str:
    """Tagging happens on a fresh main that already carries the merged release."""
    current = _run('git', 'rev-parse', '--abbrev-ref', 'HEAD')
    if current != 'main':
        _error(f'tagging happens on main - run: git checkout main (now on {current})')
    _check_tree_clean()
    _run('git', 'pull', '--ff-only')
    _run('git', 'fetch', '--tags', 'origin')
    version = _current_version()
    if f'## {version}' not in CHANGELOG.read_text(encoding='utf-8'):
        _error(f'CHANGELOG.md has no "## {version}" section - is the PR merged?')
    _ok(f'main carries v{version} with its changelog section')
    return version


def _confirm_tag(version: str, commands: Sequence[Command]) -> None:
    head = _run('git', 'log', '-1', '--format=%h %s')
    ladder = '\n'.join(_render_commands(commands, ''))
    console.print()
    console.print(
        Panel(
            f'Tag [bold]v{version}[/] on:\n  {escape(head)}\n\n'
            f'{ladder}\n\n'
            '[dim]The tag push triggers: build -> PyPI -> GitHub Release.[/]',
            title=f'Tag v{version}',
            border_style='cyan',
        )
    )
    if not Confirm.ask('  Tag and push?', default=False):
        _abort('Aborted - nothing tagged.')


def _tag_flow() -> None:
    console.print()
    console.print('  [bold]🔍 Preflight for tagging[/]')
    _check_tools()
    version = _check_main_ready()
    _check_tag_free(f'v{version}')

    commands: tuple[Command, ...] = (
        ('git', 'tag', f'v{version}'),
        ('git', 'push', 'origin', f'v{version}'),
    )
    _confirm_tag(version, commands)
    for cmd in commands:
        _run(*cmd, echo=True)
    console.print()
    console.print(
        Panel(
            f'v{version} is on its way:\n{ACTIONS_URL}',
            title='🎉 Released',
            border_style='green',
        )
    )


def main() -> None:
    """Route to the release wizard or the tag flow."""
    if len(sys.argv) != 2 or not sys.argv[1]:  # noqa: PLR2004
        console.print(r'  [yellow]Usage:[/] task release -- \[major|minor|patch|X.Y.Z]')
        console.print(
            '         task release:tag   [dim](after the release PR is merged)[/]'
        )
        sys.exit(1)
    if sys.argv[1] == 'tag':
        _tag_flow()
        return
    _release_flow(sys.argv[1])


if __name__ == '__main__':
    main()
