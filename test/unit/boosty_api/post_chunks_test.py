"""Regression tests for tolerant parsing of unknown post chunk types."""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter, ValidationError

from boosty_downloader.src.infrastructure.boosty_api.models.post.base_post_data import (
    BasePostData,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataListDTO,
    BoostyPostDataTextDTO,
    BoostyPostDataUnknownDTO,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_list import (
    BoostyListItemType,
    BoostyListStyle,
    BoostyPostDataListDataItemDTO,
)
from boosty_downloader.src.infrastructure.boosty_api.models.unknown_value import (
    BoostyUnknownValue,
)

CHUNK_ADAPTER: TypeAdapter[BasePostData] = TypeAdapter(BasePostData)


def test_unknown_chunk_type_parses_as_unknown():
    chunk = CHUNK_ADAPTER.validate_python({'type': 'super_new_thing', 'payload': 1})

    assert isinstance(chunk, BoostyPostDataUnknownDTO)
    assert chunk.type == 'super_new_thing'


def test_known_chunk_still_parses_exactly():
    chunk = CHUNK_ADAPTER.validate_python(
        {'type': 'text', 'content': 'hello', 'modificator': ''}
    )

    assert isinstance(chunk, BoostyPostDataTextDTO)


def test_known_chunk_with_broken_body_still_fails():
    with pytest.raises(ValidationError):
        CHUNK_ADAPTER.validate_python({'type': 'ok_video'})


def test_new_list_style_keeps_raw_word():
    list_chunk = BoostyPostDataListDTO.model_validate(
        {'type': 'list', 'items': [], 'style': 'checklist'}
    )

    assert list_chunk.style == BoostyUnknownValue(raw='checklist')


def test_known_list_style_parses_exactly():
    list_chunk = BoostyPostDataListDTO.model_validate(
        {'type': 'list', 'items': [], 'style': 'ordered'}
    )

    assert list_chunk.style is BoostyListStyle.ordered


def test_absent_list_style_stays_none():
    list_chunk = BoostyPostDataListDTO.model_validate({'type': 'list', 'items': []})

    assert list_chunk.style is None


def test_known_list_item_type_parses_exactly():
    item = BoostyPostDataListDataItemDTO.model_validate(
        {'type': 'text', 'content': 'hi'}
    )

    assert item.type is BoostyListItemType.text
