"""Text chunks keep the author's line breaks on the way to the domain."""

from __future__ import annotations

import json

from boosty_downloader.application.mappers.link_header_text import (
    to_domain_text_chunk,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataTextDTO,
)


def _text(
    text: str,
    *,
    block_style: str = 'unstyled',
    style_ranges: list[list[int]] | None = None,
    modificator: str = '',
) -> BoostyPostDataTextDTO:
    """A text chunk as the API sends it: a JSON triple in `content`."""
    return BoostyPostDataTextDTO(
        type='text',
        content=json.dumps([text, block_style, style_ranges or []]),
        modificator=modificator,
    )


def test_a_line_break_inside_the_text_becomes_its_own_fragment() -> None:
    """Glued to the text, a break collapsed into a space on the page."""
    fragments = to_domain_text_chunk(_text('line one\nline two'))

    assert [f.text for f in fragments] == ['line one', '\n', 'line two']


def test_the_pieces_around_a_break_keep_their_style_and_heading_level() -> None:
    fragments = to_domain_text_chunk(
        _text('Bold\nplain', block_style='header-two', style_ranges=[[0, 0, 4]])
    )

    assert [f.text for f in fragments] == ['Bold', '\n', 'plain']
    assert [f.style.bold for f in fragments] == [True, False, False]
    assert {f.header_level for f in fragments} == {2}


def test_a_block_end_with_text_ends_in_a_separate_break() -> None:
    fragments = to_domain_text_chunk(_text('para', modificator='BLOCK_END'))

    assert [f.text for f in fragments] == ['para', '\n']
