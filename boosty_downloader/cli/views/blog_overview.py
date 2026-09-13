"""
The check overview: what each tier gives, where you stand, what the rest costs.

Colors carry one meaning each and never stand alone - the text reads the
same without them: green = open to you, yellow = money, red = locked,
dim = secondary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.console import Group
from rich.markup import escape
from rich.rule import Rule
from rich.table import Table

from boosty_downloader.cli.views.media import media_line
from boosty_downloader.cli.views.text import bold_count, plural, price, price_range

if TYPE_CHECKING:
    from datetime import datetime

    from rich.console import RenderableType

    from boosty_downloader.application.blog_overview import (
        BlogOverview,
        TierStep,
        UnlockCost,
    )


def render_blog_overview(
    overview: BlogOverview, *, now: datetime, show_locked: bool = False
) -> RenderableType:
    """
    Build the overview block shown after a blog listing.

    ``now`` is injected so "last post N days ago" is testable.
    ``show_locked`` lists every title this account cannot open.
    """
    title = Rule(title=f'boosty.to/{escape(overview.author_name)}', style='dim')
    if overview.total_posts == 0:
        return Group(title, 'No posts found.', Rule(style='dim'))

    parts: list[RenderableType] = [title, _header_line(overview)]
    if overview.first_post_at and overview.last_post_at:
        parts.append(_dates_line(overview.first_post_at, overview.last_post_at, now))
    parts += [
        '',
        'What each tier gives [dim](a higher tier includes the lower ones)[/dim]',
        _ladder_table(overview),
        '',
        _for_you_line(overview),
        '',
        f'Media in your posts: {media_line(overview.media)}',
    ]
    if show_locked and overview.locked_post_titles:
        parts += ['', *_locked_lines(overview.locked_post_titles)]
    parts.append(Rule(style='dim'))
    return Group(*parts)


def _header_line(overview: BlogOverview) -> str:
    line = (
        f'{bold_count(overview.total_posts, "post")}, '
        f'[green]{overview.accessible_posts} accessible to you[/green]'
    )
    locked = overview.total_posts - overview.accessible_posts
    if locked:
        line += f', [red]{locked} locked[/red]'
    return line


def _dates_line(first: datetime, last: datetime, now: datetime) -> str:
    return (
        f'[dim]{first:%Y-%m-%d} to {last:%Y-%m-%d}, '
        f'last post {_days_ago(now, last)}[/dim]'
    )


def _days_ago(now: datetime, last: datetime) -> str:
    days = (now.date() - last.astimezone(now.tzinfo).date()).days
    if days <= 0:
        return 'today'
    if days == 1:
        return 'yesterday'
    return f'{days} days ago'


@dataclass(frozen=True, slots=True)
class _LadderRow:
    name: str
    price: str
    adds: str
    posts: int
    per_post: str
    # This account stands here: the highest rung fully open to it.
    yours: bool


def _ladder_rows(overview: BlogOverview) -> list[_LadderRow]:
    """From "no subscription" up to "everything", one row per rung."""
    singles = overview.single_purchases
    # With everything open the account stands on the top rung, whichever it is.
    stands_on_top = overview.accessible_posts == overview.total_posts
    rows = [
        _LadderRow(
            name='No tier',
            price='free',
            adds='-',
            posts=overview.free_posts,
            per_post='',
            yours=overview.your_tier is None and not (stands_on_top and singles.posts),
        )
    ]
    rows += [
        _LadderRow(
            name=escape(tier.tier),
            price='free tier' if tier.price == 0 else f'{price(tier.price)}/mo',
            adds=str(tier.adds),
            posts=tier.posts,
            per_post=_per_post(
                tier.purchasable, tier.adds, tier.min_post_price, tier.max_post_price
            ),
            yours=tier.tier == overview.your_tier
            and not (stands_on_top and singles.posts),
        )
        for tier in overview.tiers
    ]
    if singles.posts:
        rows.append(
            _LadderRow(
                name='Everything',
                price=f'+ {price(singles.total)} once',
                adds=str(singles.posts),
                posts=overview.total_posts,
                per_post=price_range(singles.min_price, singles.max_price),
                yours=stands_on_top,
            )
        )
    return rows


def _per_post(sold: int, of: int, low: float, high: float) -> str:
    """'200-1000 RUB (14/18)': the price range, and the count when not all are sold."""
    if not sold:
        return ''
    suffix = '' if sold == of else f' ({sold}/{of})'
    return price_range(low, high) + suffix


def _ladder_table(overview: BlogOverview) -> Table:
    table = Table(
        box=None,
        show_header=True,
        header_style='bold',
        show_edge=False,
        pad_edge=False,
        padding=(0, 2, 0, 0),
    )
    table.add_column('')
    table.add_column('Tier')
    table.add_column('Price')
    table.add_column('Adds', justify='right')
    table.add_column('Posts', justify='right', style='bold')
    table.add_column('Of blog', justify='right')
    table.add_column('Per post', style='dim')
    for row in _ladder_rows(overview):
        share = row.posts / overview.total_posts
        table.add_row(
            '[green]✔[/green]' if row.yours else '',
            row.name,
            row.price if row.price == 'free' else f'[yellow]{row.price}[/yellow]',
            row.adds,
            str(row.posts),
            f'{share:.0%}',
            row.per_post,
        )
    return table


def _for_you_line(overview: BlogOverview) -> str:
    total = overview.total_posts
    if overview.accessible_posts == total:
        return f'For you: [green]all {total} posts open[/green].'
    share = overview.accessible_posts / total
    line = (
        f'For you: [green]{overview.accessible_posts} of {total} posts open '
        f'({share:.0%})[/green].'
    )
    needs = _cost_parts(overview.remaining_cost)
    if needs:
        line += ' Everything needs ' + ' + '.join(needs) + '.'
    return line


def _cost_parts(cost: UnlockCost) -> list[str]:
    parts: list[str] = []
    if cost.top_tier is not None:
        parts.append(_tier_cost(cost.top_tier))
    if cost.one_off_posts:
        parts.append(
            f'[yellow]{price(cost.one_off_total)} one-off[/yellow] '
            f'({plural(cost.one_off_posts, "post")})'
        )
    return parts


def _tier_cost(step: TierStep) -> str:
    tier = escape(step.tier)
    if step.price == 0:
        return f'{tier} (free tier)'
    return f'[yellow]{price(step.price)}/mo[/yellow] ({tier})'


def _locked_lines(titles: tuple[str, ...]) -> list[str]:
    lines = [f'[bold]Locked posts ({len(titles)})[/bold]']
    lines += [
        f'[dim]  {escape(title.strip()) or "(no title)"}[/dim]' for title in titles
    ]
    return lines
