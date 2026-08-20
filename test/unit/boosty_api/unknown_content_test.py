"""Tests for the generic unknown-content walk."""

from __future__ import annotations

from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataListDTO,
)
from boosty_downloader.infrastructure.boosty_api.models.unknown_content import (
    UnknownContent,
    collect_unknown_content,
)


def test_clean_tree_yields_nothing():
    chunk = BoostyPostDataListDTO.model_validate(
        {
            'type': 'list',
            'style': 'ordered',
            'items': [{'data': [{'type': 'text', 'content': 'x'}]}],
        }
    )

    assert collect_unknown_content(chunk) == set()


def test_wrapper_is_found_at_any_depth():
    chunk = BoostyPostDataListDTO.model_validate(
        {
            'type': 'list',
            'items': [
                {'items': [{'items': [{'data': [{'type': 'weird', 'content': ''}]}]}]}
            ],
        }
    )

    assert collect_unknown_content(chunk) == {
        UnknownContent(path='items[0].items[0].items[0].data[0].type', raw='weird')
    }
