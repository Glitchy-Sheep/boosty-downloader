"""Text helpers behind the views."""

from __future__ import annotations

import pytest

from boosty_downloader.cli.views.text import bold_count, duration, plural, price


@pytest.mark.parametrize(
    ('value', 'expected'),
    [
        pytest.param(10, '10 RUB', id='whole'),
        pytest.param(9.5, '9.50 RUB', id='fractional-keeps-two-digits'),
        pytest.param(float('inf'), 'inf RUB', id='absurd-value-does-not-crash'),
    ],
)
def test_price(value: float, expected: str):
    assert price(value) == expected


def test_plural_and_bold_count_agree_on_one():
    assert plural(1, 'post') == '1 post'
    assert plural(2, 'post') == '2 posts'
    assert bold_count(1, 'post') == '[bold]1[/bold] post'
    assert bold_count(0, 'post') == '[bold]0[/bold] posts'


@pytest.mark.parametrize(
    ('seconds', 'expected'),
    [
        pytest.param(37.9, '37s', id='seconds'),
        pytest.param(252, '4m 12s', id='minutes'),
        pytest.param(3780, '1h 03m', id='hours'),
    ],
)
def test_duration_reads_like_a_clock(seconds: float, expected: str):
    assert duration(seconds) == expected
