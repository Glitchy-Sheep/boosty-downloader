"""Literal prefix search using the index's SQLite FTS5 tokenizer."""

from __future__ import annotations

from contextlib import closing
from sqlite3 import connect
from typing import Final

from boosty_downloader.infrastructure.library.index_projection import fold_search_text

HIT_START: Final = '\x02'
HIT_END: Final = '\x03'


def search_expression(value: str) -> str:
    """Quote distinct unicode61 terms as prefixes; token-free input adds no filter."""
    if not value:
        return ''
    with closing(connect(':memory:')) as connection:
        connection.text_factory = bytes
        connection.execute(
            "CREATE VIRTUAL TABLE query_tokens USING fts5(value, tokenize='unicode61 remove_diacritics 2')"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE query_vocab USING fts5vocab(query_tokens, 'row')"
        )
        connection.execute(
            'INSERT INTO query_tokens(value) VALUES (?)', (fold_search_text(value),)
        )
        terms = connection.execute('SELECT term FROM query_vocab ORDER BY term')
        return ' AND '.join(_prefix_term(row[0]) for row in terms)


def _prefix_term(value: bytes) -> str:
    # SQLite truncates tokens at 32768 bytes, possibly inside a UTF-8 character.
    term = value.decode('utf-8', errors='ignore').replace('"', '""')
    return f'"{term}"*'
