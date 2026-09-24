"""
Weekly repository report for Telegram, as HTML.

Collects the last 7 days through the gh CLI: canary and CI state, what the
Boosty API added since the committed schema, pull requests, issues, PyPI
downloads and stars. Prints the message to
stdout. .github/workflows/weekly-report.yaml sends it through a Telegram bot.

Run locally: uv run python scripts/weekly_report.py
"""

from __future__ import annotations

import html
import json
import re
import subprocess
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = 'Glitchy-Sheep/boosty-downloader'
PACKAGE = 'boosty-downloader'
RENOVATE = 'app/renovate'
MAX_ITEMS = 8

Item = dict[str, Any]

CONCLUSION_ICONS = {'success': '✅', 'failure': '❌', 'cancelled': '⚪'}
# The canary uploads what the API added since docs/api/boosty-api.yaml.
CHANGES_ARTIFACT = 'api-changes'
# New things first, then what changed in the keys the schema knows.
NEW_KINDS = ('new_chunk', 'new_key')
CHANGE_LINES = {
    'new_chunk': '- new content type <code>{detail}</code>: posts lose it',
    'new_key': '- <code>{where}</code> ({detail})',
    'new_type': '- <code>{where}</code>: {detail}',
    'new_value': '- <code>{where}</code>: new value <code>{detail}</code>',
}
REPO_URL = f'https://github.com/{REPO}'
PYPI_URL = f'https://pypi.org/project/{PACKAGE}/'
PYPISTATS_URL = f'https://pypistats.org/packages/{PACKAGE}'
PEPY_URL = f'https://pepy.tech/projects/{PACKAGE}'
SCHEMA_URL = f'{REPO_URL}/blob/main/docs/api/boosty-api.yaml'
# Total downloads need an API key at pepy.tech; its badge does not.
PEPY_BADGE = f'https://static.pepy.tech/badge/{PACKAGE}'


def _escape(text: str) -> str:
    # The Telegram action decodes HTML entities once before sending:
    # one escape would turn back into raw `<` and break the message.
    return html.escape(html.escape(text))


def _gh(*args: str) -> Any:  # noqa: ANN401 - gh returns arbitrary JSON
    result = subprocess.run(['gh', *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        return []
    return json.loads(result.stdout or '[]')


def _list(
    kind: str, state: str, search: str = '', fields: str = 'number'
) -> list[Item]:
    """List pull requests or issues of the repo, up to 200."""
    args = [kind, 'list', '--repo', REPO, '--state', state, '--limit', '200']
    if search:
        args += ['--search', search]
    return _gh(*args, '--json', fields)


def _parse_time(value: str) -> datetime:
    # Python 3.10 does not read the trailing Z that GitHub sends.
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _a(url: str, text: str) -> str:
    """Link text that is already HTML."""
    return f'<a href="{url}">{text}</a>'


def _search(page: str, query: str) -> str:
    """Build a GitHub search url of this repo, e.g. merged PRs since a day."""
    return f'{REPO_URL}/{page}?q={urllib.parse.quote(query)}'


def _workflow(file: str) -> str:
    return f'{REPO_URL}/actions/workflows/{file}'


def _link(item: Item) -> str:
    return f'<a href="{item["url"]}">{_escape(item["title"])}</a> #{item["number"]}'


def _bullets(items: list[Item]) -> list[str]:
    lines = [f'• {_link(item)}' for item in items[:MAX_ITEMS]]
    if len(items) > MAX_ITEMS:
        lines.append(f'• … and {len(items) - MAX_ITEMS} more')
    return lines


def _latest_run(workflow: str) -> Item | None:
    fields = 'databaseId,conclusion,status,url,createdAt'
    runs = _gh('run', 'list', '--repo', REPO, '--workflow', workflow,
               '--branch', 'main', '--limit', '1', '--json', fields)  # fmt: skip
    return runs[0] if runs else None


def _run_text(run: Item | None, since: datetime) -> str:
    if run is None:
        return '⚪ no runs yet'
    when = _parse_time(run['createdAt'])
    stale = '' if when >= since else ', older than a week'
    icon = CONCLUSION_ICONS.get(run['conclusion'], '⏳')
    state = run['conclusion'] or run['status']
    return f'{icon} <a href="{run["url"]}">{state}</a> ({when:%d.%m}{stale})'


def _health(since: datetime, canary: Item | None) -> list[str]:
    drift = _list('issue', 'open', 'label:api-drift', 'number,title,url')
    ci = _latest_run('ci.yaml')
    lines = [
        '🩺 <b>Health</b>',
        f'{_a(_workflow("canary.yaml"), "Canary")}: {_run_text(canary, since)}',
        f'{_a(_workflow("ci.yaml"), "CI on main")}: {_run_text(ci, since)}',
    ]
    return lines + [f'⚠️ API drift: {_link(issue)}' for issue in drift]


def _download_changes(run: Item) -> list[Item] | None:
    """Return the change list the canary run uploaded, or None without one."""
    with tempfile.TemporaryDirectory() as folder:
        result = subprocess.run(
            ['gh', 'run', 'download', str(run['databaseId']), '--repo', REPO,
             '--name', CHANGES_ARTIFACT, '--dir', folder],
            capture_output=True, text=True, check=False,
        )  # fmt: skip
        if result.returncode != 0:
            return None
        return json.loads((Path(folder) / f'{CHANGES_ARTIFACT}.json').read_text())


def _change_lines(changes: list[Item]) -> list[str]:
    return [
        CHANGE_LINES[c['kind']].format(
            where=_escape(c['where']), detail=_escape(c['detail'])
        )
        for c in changes[:MAX_ITEMS]
    ]


def _api_changes(canary: Item | None) -> list[str]:
    """Additions that break nothing yet; the canary opens an issue for the rest."""
    changes = _download_changes(canary) if canary else None
    # The title opens the canary run that found the changes.
    title = f'🔭 <b>{_a(canary["url"], "API changes") if canary else "API changes"}</b>'
    if changes is None:
        return [f'{title}: no list in the last canary run']
    if not changes:
        return [f'{title}: nothing new']
    new = [c for c in changes if c['kind'] in NEW_KINDS]
    changed = [c for c in changes if c['kind'] not in NEW_KINDS]
    lines = [f'{title}: {len(changes)} new']
    if new:
        lines += ['', '<b>New:</b>', *_change_lines(new)]
    if changed:
        lines += ['', '<b>Changes:</b>', *_change_lines(changed)]
    accept = f'<code>{_escape("task api:schema -- <blog>")}</code>'
    schema = _a(SCHEMA_URL, 'the schema')
    return [*lines, '', f'Accept: {accept}, commit {schema}']


def _github_stats(day: str) -> list[str]:
    merged = _list('pr', 'merged', f'merged:>={day}')
    opened = _list('pr', 'all', f'created:>={day}')
    still_open = _list('pr', 'open', fields='number,author')
    bots = sum(pr['author']['login'] == RENOVATE for pr in still_open)
    merged_url = _search('pulls', f'is:pr is:merged merged:>={day}')
    opened_url = _search('pulls', f'is:pr created:>={day}')
    renovate_url = _search('pulls', f'is:pr is:open author:{RENOVATE}')
    return [
        '🔀 <b>GitHub Stats</b>',
        f'- {_a(merged_url, "Merged PRs")}: <b>{len(merged)}</b>',
        (
            f'- {_a(opened_url, "Opened PRs")}: <b>{len(opened)}</b> · '
            f'{_a(f"{REPO_URL}/pulls", "open now")}: <b>{len(still_open)}</b> '
            f'({_a(renovate_url, "Renovate")}: {bots})'
        ),
    ]


def _issues(day: str) -> list[str]:
    new = _list('issue', 'all', f'created:>={day}', 'number,title,url')
    still_open = _list('issue', 'open')
    lines = [
        '🐛 <b>New Issues</b>',
        f'- {_a(f"{REPO_URL}/issues", "Currently opened")}: <b>{len(still_open)}</b>',
        (
            f'- {_a(_search("issues", f"is:issue created:>={day}"), "Opened this week")}: '
            f'<b>{len(new)}</b>'
        ),
    ]
    if new:
        lines += ['', 'Issues of the week:', *_bullets(new)]
    return lines


def _fetch(url: str) -> bytes | None:
    try:
        # Only the fixed https urls of this module get here. pepy.tech
        # answers 403 to the default Python user agent.
        request = urllib.request.Request(url, headers={'User-Agent': PACKAGE})  # noqa: S310
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310
            return response.read()
    except OSError:
        return None


def _number(value: int) -> str:
    return f'{value:,}'.replace(',', ' ')


def _pypi_recent() -> tuple[str, str]:
    """Return downloads of the last month and the last week, from pypistats."""
    body = _fetch(f'https://pypistats.org/api/packages/{PACKAGE}/recent')
    try:
        data = json.loads(body or b'')['data']
        return _number(data['last_month']), _number(data['last_week'])
    except (ValueError, KeyError):
        return 'n/a', 'n/a'


def _pypi_total() -> str:
    """Return all-time downloads as the pepy.tech badge rounds them, e.g. `21k`."""
    badge = (_fetch(PEPY_BADGE) or b'').decode(errors='replace')
    values = re.findall(r'>([0-9][0-9.,]*[kKmM]?)<', badge)
    return values[-1] if values else 'n/a'


def _audience() -> list[str]:
    counts = _gh('api', f'repos/{REPO}', '--jq', '[.stargazers_count, .forks_count]')
    stars, forks = counts or ('n/a', 'n/a')
    month, week = _pypi_recent()
    return [
        '📈 <b>Audience</b>',
        f'- 🐍 {_a(PEPY_URL, "PyPI downloads total")}: <b>{_pypi_total()}</b>',
        f'- 🐍 {_a(PYPISTATS_URL, "PyPI downloads last month")}: <b>{month}</b>',
        f'- 🐍 {_a(PYPISTATS_URL, "PyPI downloads last week")}: <b>{week}</b>',
        '',
        f'- ⭐ {_a(f"{REPO_URL}/stargazers", "Stars")}: <b>{stars}</b>',
        f'- 🍴 {_a(f"{REPO_URL}/forks", "Forks")}: <b>{forks}</b>',
    ]


def build_report(now: datetime) -> str:
    """Return the report for the 7 days before now, as Telegram HTML."""
    since = now - timedelta(days=7)
    day = f'{since:%Y-%m-%d}'
    title = [
        f'📊 <b>{_a(REPO_URL, PACKAGE)}</b> · {_a(PYPI_URL, "PyPI")}',
        '',
        f'<blockquote>week {since:%d.%m} - {now:%d.%m}</blockquote>',
    ]
    canary = _latest_run('canary.yaml')
    blocks = [
        title,
        _health(since, canary),
        _api_changes(canary),
        _github_stats(day),
        _issues(day),
        _audience(),
    ]
    return '\n\n'.join('\n'.join(block) for block in blocks)


if __name__ == '__main__':
    print(build_report(datetime.now(timezone.utc)))
