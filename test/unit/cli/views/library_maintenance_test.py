"""Offline maintenance messages keep user-controlled paths and errors literal."""

from pathlib import Path

from rich.text import Text

from boosty_downloader.cli.views.library_maintenance import (
    render_reindex_failure,
    render_reindex_result,
)


def test_reindex_result_preserves_brackets_in_the_index_path() -> None:
    path = Path('library[red]/index.db')
    result = Text.from_markup(render_reindex_result(authors=1, posts=2, path=path))
    assert result.plain == f'Rebuilt library index: 1 author, 2 posts. Index: {path}'


def test_reindex_failure_keeps_record_error_markup_literal() -> None:
    path = Path('library[red]/index.db')
    reason = '[bold]invalid record[/bold]'
    result = Text.from_markup(render_reindex_failure(path=path, reason=reason))
    assert f'{path}: {reason}' in result.plain
    assert '--cache-dir' in result.plain
