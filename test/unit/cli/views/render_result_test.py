"""Offline render summaries preserve literal paths and diagnostic text."""

from pathlib import Path

import pytest
from rich.text import Text

from boosty_downloader.cli.views.render_result import (
    render_pages_failure,
    render_pages_result,
)


@pytest.mark.parametrize(
    ('pages', 'summary'), [(0, '0 pages'), (1, '1 page'), (12, '12 pages')]
)
def test_result_counts_pages_and_escapes_library_name(pages: int, summary: str) -> None:
    root = Path('saved/[red]library[/red]')

    output = Text.from_markup(render_pages_result(pages=pages, root=root)).plain

    assert output == f'Rendered {summary}. Library: {root}'


def test_failure_keeps_path_and_reason_literal() -> None:
    root = Path('saved/[bold]library[/bold]')
    reason = '[red]post.json[/red] is invalid'

    output = Text.from_markup(render_pages_failure(root=root, reason=reason)).plain

    assert output == (
        f'Cannot render saved pages in {root}: {reason}. '
        'Check the saved records and library folder permissions.'
    )
