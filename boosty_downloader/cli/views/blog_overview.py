"""The check overview: how a blog unlocks, what it holds and what it costs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.console import Group
from rich.markup import escape
from rich.rule import Rule
from rich.table import Table

from boosty_downloader.cli.views.media import media_table
from boosty_downloader.cli.views.text import bold_count, plural, price

if TYPE_CHECKING:
    from datetime import datetime

    from rich.console import RenderableType

    from boosty_downloader.application.blog_overview import (
        AccessGroup,
        BlogOverview,
        TierStep,
        UnlockCost,
    )


def render_blog_overview(overview: BlogOverview, *, now: datetime) -> RenderableType:
    """
    Build the overview block shown after a blog listing.

    ``now`` is injected so "last post N days ago" is testable.
    """
    title = Rule(title=f'boosty.to/{escape(overview.author_name)}', style='dim')
    if overview.total_posts == 0:
        return Group(title, 'No posts found.', Rule(style='dim'))

    parts: list[RenderableType] = [
        title,
        (
            f'{bold_count(overview.total_posts, "post")}, '
            f'[bold]{overview.accessible_posts}[/bold] accessible to you'
        ),
    ]
    if overview.first_post_at and overview.last_post_at:
        parts.append(_dates_line(overview.first_post_at, overview.last_post_at, now))
    parts += [
        '',
        _access_table(overview.access_groups),
        '',
        '[bold]Media in accessible posts[/bold]',
        media_table(overview.media),
        '',
        *_cost_lines(overview),
    ]
    if overview.locked_post_titles:
        parts += ['', *_locked_lines(overview.locked_post_titles)]
    parts.append(Rule(style='dim'))
    return Group(*parts)


# A big blog locks hundreds of posts: a taste of the titles is enough.
_LOCKED_TITLES_SHOWN = 20


def _locked_lines(titles: tuple[str, ...]) -> list[str]:
    lines = [f'[bold]Locked posts ({len(titles)})[/bold]']
    lines += [
        f'[dim]  {escape(title.strip()) or "(no title)"}[/dim]'
        for title in titles[:_LOCKED_TITLES_SHOWN]
    ]
    hidden = len(titles) - _LOCKED_TITLES_SHOWN
    if hidden > 0:
        lines.append(f'[dim]  and {hidden} more[/dim]')
    return lines


def _dates_line(first: datetime, last: datetime, now: datetime) -> str:
    return (
        f'[bold]{first:%Y-%m-%d}[/bold] to [bold]{last:%Y-%m-%d}[/bold], '
        f'last post {_days_ago(now, last)}'
    )


def _days_ago(now: datetime, last: datetime) -> str:
    days = (now.date() - last.astimezone(now.tzinfo).date()).days
    if days <= 0:
        return 'today'
    if days == 1:
        return 'yesterday'
    return f'{days} days ago'


def _access_table(groups: list[AccessGroup]) -> Table:
    table = Table(
        box=None,
        show_header=True,
        header_style='bold',
        show_edge=False,
        pad_edge=False,
        padding=(0, 3, 0, 0),
    )
    table.add_column('Access')
    table.add_column('Price')
    table.add_column('Posts', justify='right')
    table.add_column('Locked for you', justify='right')
    for group in groups:
        table.add_row(
            _group_label(group),
            _group_price(group),
            f'[bold]{group.posts}[/bold]',
            _locked_cell(group),
        )
    return table


def _group_label(group: AccessGroup) -> str:
    if group.tier is not None:
        return escape(group.tier)
    return 'Single purchase' if group.post_price > 0 else 'Free'


def _group_price(group: AccessGroup) -> str:
    if group.tier is None:
        return f'{price(group.post_price)} each' if group.post_price > 0 else '-'
    label = 'free tier' if group.tier_price == 0 else f'{price(group.tier_price)}/mo'
    if group.post_price > 0:
        label += f' or {price(group.post_price)} each'
    return label


def _locked_cell(group: AccessGroup) -> str:
    locked = group.posts - group.accessible
    return f'[red]{locked}[/red]' if locked else '-'


def _cost_lines(overview: BlogOverview) -> list[str]:
    """Say what the blog is worth when you have it all, or what the rest costs."""
    if overview.accessible_posts == overview.total_posts:
        return [
            _full_cost_line(overview.full_access_cost),
            'You already have access to everything',
        ]
    return [_remaining_cost_line(overview.remaining_cost)]


def _full_cost_line(cost: UnlockCost) -> str:
    if cost.is_free:
        return 'Everything here is free'
    parts: list[str] = []
    if cost.top_tier is not None:
        parts.append(_tier_text(cost.top_tier))
    parts += _one_off_parts(cost)
    return 'Full access costs ' + ' + '.join(parts)


def _remaining_cost_line(cost: UnlockCost) -> str:
    if cost.is_free:
        return 'To unlock the rest: nothing to buy'
    parts: list[str] = []
    if len(cost.tiers) == 1:
        parts.append(_tier_text(cost.tiers[0]))
    elif cost.tiers:
        # Every rung shows what it opens: a gimmick top tier must not hide
        # that the cheap one already opens most of the blog.
        rungs = [
            f'{_tier_text(step)} opens {plural(step.posts, "post")}'
            for step in cost.tiers[:-1]
        ]
        rungs.append(f'{_tier_text(cost.tiers[-1])} opens all {cost.tiers[-1].posts}')
        parts.append(', '.join(rungs))
    parts += _one_off_parts(cost)
    return 'To unlock the rest: ' + ' + '.join(parts)


def _tier_text(step: TierStep) -> str:
    tier = escape(step.tier)
    if step.price == 0:
        return f'{tier} (free tier)'
    return f'{price(step.price)}/mo ({tier})'


def _one_off_parts(cost: UnlockCost) -> list[str]:
    if not cost.one_off_posts:
        return []
    return [
        f'{price(cost.one_off_total)} one-off ({plural(cost.one_off_posts, "post")})'
    ]
