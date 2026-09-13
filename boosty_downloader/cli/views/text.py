"""Small text helpers shared by the views."""

from __future__ import annotations


def amount(value: float) -> str:
    """Format a number of rubles without trailing zeros: 10, 9.50."""
    # float() first: int.is_integer needs 3.12, and inf/nan must not crash.
    if float(value).is_integer():
        return str(int(value))
    return f'{value:.2f}'


def price(value: float) -> str:
    """Format rubles with the currency: 10 RUB, 9.50 RUB."""
    return f'{amount(value)} RUB'


def price_range(low: float, high: float) -> str:
    """Format a price range: '200-1000 RUB', or '1000 RUB' when both ends match."""
    if low == high:
        return price(high)
    return f'{amount(low)}-{amount(high)} RUB'


def plural(count: int, noun: str) -> str:
    """'1 post', '2 posts'."""
    return f'{count} {noun}' if count == 1 else f'{count} {noun}s'


def bold_count(count: int, noun: str) -> str:
    """Count a noun like plural, with the number in bold markup."""
    return (
        f'[bold]{count}[/bold] {noun}'
        if count == 1
        else f'[bold]{count}[/bold] {noun}s'
    )


def duration(seconds: float) -> str:
    """'37s', '4m 12s', '1h 03m' - reads like a clock."""
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f'{hours}h {minutes:02d}m'
    if minutes:
        return f'{minutes}m {secs:02d}s'
    return f'{secs}s'
