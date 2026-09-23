"""
Weekly repository report for Telegram, as HTML.

Collects the last 7 days through the gh CLI: canary and CI state, pull
requests, issues, releases, PyPI downloads and stars. Prints the message to
stdout. .github/workflows/weekly-report.yaml sends it through a Telegram bot.

Run locally: uv run python scripts/weekly_report.py
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any

REPO = 'Glitchy-Sheep/boosty-downloader'
PACKAGE = 'boosty-downloader'
RENOVATE = 'app/renovate'
MAX_ITEMS = 8

Item = dict[str, Any]

CONCLUSION_ICONS = {'success': '✅', 'failure': '❌', 'cancelled': '⚪'}


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


def _link(item: Item) -> str:
    return f'<a href="{item["url"]}">{escape(item["title"])}</a> #{item["number"]}'


def _bullets(items: list[Item]) -> list[str]:
    lines = [f'• {_link(item)}' for item in items[:MAX_ITEMS]]
    if len(items) > MAX_ITEMS:
        lines.append(f'• … and {len(items) - MAX_ITEMS} more')
    return lines


def _last_run(workflow: str, since: datetime) -> str:
    fields = 'conclusion,status,url,createdAt'
    runs = _gh('run', 'list', '--repo', REPO, '--workflow', workflow,
               '--branch', 'main', '--limit', '1', '--json', fields)  # fmt: skip
    if not runs:
        return '⚪ no runs yet'
    run = runs[0]
    when = _parse_time(run['createdAt'])
    stale = '' if when >= since else ', older than a week'
    icon = CONCLUSION_ICONS.get(run['conclusion'], '⏳')
    state = run['conclusion'] or run['status']
    return f'{icon} <a href="{run["url"]}">{state}</a> ({when:%d.%m}{stale})'


def _health(since: datetime) -> list[str]:
    drift = _list('issue', 'open', 'label:api-drift', 'number,title,url')
    lines = [
        '🩺 <b>Health</b>',
        f'Canary: {_last_run("canary.yaml", since)}',
        f'CI on main: {_last_run("ci.yaml", since)}',
    ]
    return lines + [f'⚠️ API drift: {_link(issue)}' for issue in drift]


def _pull_requests(day: str) -> list[str]:
    fields = 'number,title,url,author'
    merged = _list('pr', 'merged', f'merged:>={day}', fields)
    opened = _list('pr', 'all', f'created:>={day}')
    still_open = _list('pr', 'open', fields=fields)
    bots = sum(pr['author']['login'] == RENOVATE for pr in still_open)
    counts = (
        f'Merged: <b>{len(merged)}</b> · opened: <b>{len(opened)}</b> · '
        f'open now: <b>{len(still_open)}</b> (Renovate: {bots})'
    )
    humans = [pr for pr in merged if pr['author']['login'] != RENOVATE]
    return ['🔀 <b>Pull requests</b>', counts, *_bullets(humans)]


def _issues(day: str) -> list[str]:
    new = _list('issue', 'all', f'created:>={day}', 'number,title,url')
    closed = _list('issue', 'closed', f'closed:>={day}')
    still_open = _list('issue', 'open')
    counts = (
        f'New: <b>{len(new)}</b> · closed: <b>{len(closed)}</b> · '
        f'open now: <b>{len(still_open)}</b>'
    )
    return ['🐛 <b>Issues</b>', counts, *_bullets(new)]


def _releases(since: datetime) -> list[str]:
    releases = _gh('release', 'list', '--repo', REPO, '--limit', '10',
                   '--json', 'tagName,publishedAt')  # fmt: skip
    fresh = [r['tagName'] for r in releases if _parse_time(r['publishedAt']) >= since]
    tags = ', '.join(f'<code>{tag}</code>' for tag in fresh) or 'none this week'
    return [f'🚀 <b>Releases</b>: {tags}']


def _pypi_downloads() -> str:
    url = f'https://pypistats.org/api/packages/{PACKAGE}/recent'
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return f'{json.load(response)["data"]["last_week"]:,}'.replace(',', ' ')
    except (OSError, ValueError, KeyError):
        return 'n/a'


def _audience() -> list[str]:
    counts = _gh('api', f'repos/{REPO}', '--jq', '[.stargazers_count, .forks_count]')
    stars, forks = counts or ('n/a', 'n/a')
    return [
        '📈 <b>Audience</b>',
        f'PyPI downloads last week: <b>{_pypi_downloads()}</b>',
        f'⭐ Stars: <b>{stars}</b> · 🍴 Forks: <b>{forks}</b>',
    ]


def build_report(now: datetime) -> str:
    """Return the report for the 7 days before now, as Telegram HTML."""
    since = now - timedelta(days=7)
    day = f'{since:%Y-%m-%d}'
    title = (
        f'📊 <b><a href="https://github.com/{REPO}">{PACKAGE}</a></b> · '
        f'week {since:%d.%m} - {now:%d.%m}'
    )
    blocks = [
        [title],
        _health(since),
        _pull_requests(day),
        _issues(day),
        _releases(since),
        _audience(),
    ]
    return '\n\n'.join('\n'.join(block) for block in blocks)


if __name__ == '__main__':
    print(build_report(datetime.now(timezone.utc)))
