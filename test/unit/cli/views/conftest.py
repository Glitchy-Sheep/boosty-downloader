"""
Render views to plain text and pin them with golden files.

The text is what the user sees minus colors: markup resolved, columns
aligned by rich at a fixed width. Goldens live in test/fixtures/views;
an intentional change of the output regenerates them:
UPDATE_GOLDEN=1 uv run pytest test/unit/cli/views - then review the diff.
"""

from __future__ import annotations

import io
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from rich.console import Console

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import RenderableType

GOLDEN_DIR = Path(__file__).parents[3] / 'fixtures' / 'views'
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


@pytest.fixture
def golden() -> Callable[[str, str], None]:
    """Compare text with test/fixtures/views/<name>.txt."""

    def check(name: str, text: str) -> None:
        path = GOLDEN_DIR / f'{name}.txt'
        if os.environ.get('UPDATE_GOLDEN') == '1':
            path.write_text(text, encoding='utf-8')
        assert text == path.read_text(encoding='utf-8')

    return check
