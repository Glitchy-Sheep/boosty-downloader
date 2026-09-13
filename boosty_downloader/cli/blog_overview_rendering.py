"""Render a BlogOverview as terminal text with rich markup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.markup import escape

if TYPE_CHECKING:
    from datetime import datetime

    from boosty_downloader.application.blog_overview import (
        AccessGroup,
        BlogOverview,
        MediaCounts,
    )


def render_blog_overview(overview: BlogOverview, *, now: datetime) -> str:
    """
    Build the multi-line summary block shown after a blog listing.

    ``now`` is injected so "last post N days ago" is testable.
    """
    if overview.total_posts == 0:
        return 'No posts found.'

    lines = [
        (
            f'Blog overview: [bold]{overview.total_posts}[/bold] '
            f'{_plural_posts(overview.total_posts)}, '
            f'[bold]{overview.accessible_posts}[/bold] accessible to you'
        ),
        '',
        'Access:',
        *(
            f'  {_group_label(group)}: {_group_counts(group)}'
            for group in overview.access_groups
        ),
        '',
        'Media in accessible posts:',
        *media_lines(overview.media),
    ]
    if overview.first_post_at and overview.last_post_at:
        lines += ['', _dates_line(overview, now=now)]
    if overview.locked_post_titles:
        lines += ['', f'Locked posts ({len(overview.locked_post_titles)}):']
        lines += [f'  - {escape(title)}' for title in overview.locked_post_titles]
    return '\n'.join(lines)


def _plural_posts(count: int) -> str:
    return 'post' if count == 1 else 'posts'


def _format_price(value: float) -> str:
    # float() first: int.is_integer needs 3.12, and inf/nan must not crash.
    if float(value).is_integer():
        return str(int(value))
    return f'{value:.2f}'


def _group_label(group: AccessGroup) -> str:
    """Human name of one way to unlock posts."""
    if group.tier is None:
        if group.post_price > 0:
            return f'Single purchase ({_format_price(group.post_price)} RUB)'
        return 'Free'
    if group.tier_price == 0:
        label = f'{escape(group.tier)} (free tier)'
    else:
        label = f'{escape(group.tier)} ({_format_price(group.tier_price)} RUB/mo)'
    if group.post_price > 0:
        label += f', or {_format_price(group.post_price)} RUB one-off'
    return label


def _group_counts(group: AccessGroup) -> str:
    posts = f'[bold]{group.posts}[/bold] {_plural_posts(group.posts)}'
    locked = group.posts - group.accessible
    if locked == 0:
        return posts
    return f'{posts} ([red]{locked} locked[/red])'


def media_lines(media: MediaCounts) -> list[str]:
    """One line per media kind, emoji-labeled - the shared column style."""
    kinds = [
        ('🖼', 'images', media.images),
        ('📄', 'files', media.files),
        ('🎬', 'boosty videos', media.boosty_videos),
        ('🔗', 'external videos', media.external_videos),
        ('🎵', 'audio', media.audio),
    ]
    return [f'  {emoji} {name}: [bold]{count}[/bold]' for emoji, name, count in kinds]


def _dates_line(overview: BlogOverview, *, now: datetime) -> str:
    first = overview.first_post_at
    last = overview.last_post_at
    if first is None or last is None:  # pragma: no cover - guarded by the caller
        return ''
    return (
        f'Posts from [bold]{first:%Y-%m-%d}[/bold] to [bold]{last:%Y-%m-%d}[/bold] '
        f'(last post {_days_ago(now, last)})'
    )


def _days_ago(now: datetime, last: datetime) -> str:
    days = (now.date() - last.astimezone(now.tzinfo).date()).days
    if days <= 0:
        return 'today'
    if days == 1:
        return 'yesterday'
    return f'{days} days ago'
