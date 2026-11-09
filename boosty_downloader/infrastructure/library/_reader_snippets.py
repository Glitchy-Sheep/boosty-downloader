"""Original-text search highlights and context without rendered markup."""

from __future__ import annotations

from re import compile as compile_pattern
from typing import Final

from boosty_downloader.domain.library import SearchMatch, SearchRun
from boosty_downloader.infrastructure.library._reader_search import HIT_END, HIT_START

_SNIPPET_BEFORE: Final = 60
_SNIPPET_AFTER: Final = 140
_HIT_MARKERS: Final = compile_pattern(f'[{HIT_START}{HIT_END}]')


def search_match(
    title_hits: str, body_hits: str, original_title: str, original_body: str
) -> SearchMatch:
    """Transfer folded hits to original text and keep context around the first body hit."""
    title = _transfer(title_hits, original_title)
    body = _snippet(_transfer(body_hits, original_body))
    return SearchMatch(_runs(title), _runs(body) if body is not None else None)


def _transfer(marked: str, original: str) -> str:
    result: list[str] = []
    offset = 0
    for index, marker in enumerate(_HIT_MARKERS.finditer(marked)):
        boundary = marker.start() - index
        result.extend((original[offset:boundary], marker.group()))
        offset = boundary
    result.append(original[offset:])
    return ''.join(result)


def _snippet(marked: str) -> str | None:
    if HIT_START not in marked:
        return None
    marked = ' '.join(marked.split())
    start = marked.index(HIT_START)
    return _snippet_head(marked[:start]) + _snippet_tail(marked[start:])


def _snippet_head(head: str) -> str:
    if len(head) <= _SNIPPET_BEFORE:
        return head
    start = head.find(' ', len(head) - _SNIPPET_BEFORE)
    return '…' + head[start + 1 :] if start >= 0 else '…'


def _snippet_tail(tail: str) -> str:
    if len(tail) <= _SNIPPET_AFTER:
        return tail
    cut = tail.rfind(' ', 0, _SNIPPET_AFTER)
    if cut <= 0:
        cut = _SNIPPET_AFTER
    if tail.count(HIT_START, 0, cut) > tail.count(HIT_END, 0, cut):
        cut = tail.index(HIT_END, cut) + 1
    elif cut == _SNIPPET_AFTER:
        boundary = tail.find(' ', cut)
        cut = boundary if boundary >= 0 else len(tail)
    return tail[:cut].rstrip() + ('…' if cut < len(tail) else '')


def _runs(marked: str) -> tuple[SearchRun, ...]:
    return tuple(
        SearchRun(part, matched=bool(index % 2))
        for index, part in enumerate(_HIT_MARKERS.split(marked))
        if part
    )
