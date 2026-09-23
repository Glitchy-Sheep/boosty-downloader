"""
Render views to plain text and check the lines the user reads.

The text is what the user sees minus colors: markup resolved, columns
aligned by rich at a fixed width. Checks ignore spacing and line wrap,
so a column width or a wrap change does not break them; wording, numbers
and order do.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pytest
from rich.console import Console

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from rich.console import RenderableType

WIDTH = 80


@pytest.fixture
def plain() -> Callable[[RenderableType], str]:
    """Render like a plain 80-column terminal without colors."""

    def render(renderable: RenderableType) -> str:
        buffer = io.StringIO()
        console = Console(
            file=buffer,
            width=WIDTH,
            color_system=None,
            force_terminal=False,
            legacy_windows=False,
            highlight=False,
            emoji=False,
        )
        console.print(renderable)
        lines = buffer.getvalue().splitlines()
        return '\n'.join(line.rstrip() for line in lines) + '\n'

    return render


def _squash(text: str) -> str:
    return ' '.join(text.split())


@pytest.fixture
def shows() -> Callable[[str, Sequence[str]], None]:
    """Check that the text holds every phrase, in this order."""

    def check(text: str, phrases: Sequence[str]) -> None:
        flat = _squash(text)
        position = 0
        for phrase in map(_squash, phrases):
            found = flat.find(phrase, position)
            assert found >= 0, f'{phrase!r} not found in order in:\n{text}'
            position = found + len(phrase)

    return check
