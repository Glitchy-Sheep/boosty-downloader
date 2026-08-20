"""Ordered lists must stay ordered on the way from the API to HTML."""

from __future__ import annotations

import pytest

from boosty_downloader.application.mappers.html_converter import (
    convert_list_to_html,
)
from boosty_downloader.application.mappers.list import to_domain_list_chunk
from boosty_downloader.domain.post_data_chunks import PostDataChunkTextualList
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_list import (
    BoostyPostDataListDTO,
)
from boosty_downloader.infrastructure.html_generator.models import HtmlListStyle

ListStyle = PostDataChunkTextualList.ListStyle


@pytest.mark.parametrize(
    ('api_style', 'expected'),
    [
        ('ordered', ListStyle.ordered),
        ('unordered', ListStyle.unordered),
        (None, ListStyle.unordered),
        ('checklist', ListStyle.unordered),
    ],
    ids=['ordered', 'unordered', 'absent', 'unknown'],
)
def test_api_list_style_lands_in_the_domain(api_style: str | None, expected: ListStyle):
    """The author's numbering used to be dropped here: every list became bullets."""
    payload: dict[str, object] = {'type': 'list', 'items': []}
    if api_style is not None:
        payload['style'] = api_style

    chunk = to_domain_list_chunk(BoostyPostDataListDTO.model_validate(payload))

    assert chunk.style is expected


@pytest.mark.parametrize(
    ('domain_style', 'expected'),
    [
        (ListStyle.ordered, HtmlListStyle.ORDERED),
        (ListStyle.unordered, HtmlListStyle.UNORDERED),
    ],
    ids=['ordered', 'unordered'],
)
def test_domain_list_style_lands_in_html(
    domain_style: ListStyle, expected: HtmlListStyle
):
    """A hardcoded UNORDERED here silently killed the numbering after mapping."""
    chunk = PostDataChunkTextualList(items=[], style=domain_style)

    assert convert_list_to_html(chunk).style is expected
