"""Regression tests for human-readable rendering of validation errors."""

from __future__ import annotations

from enum import Enum

import pytest
from pydantic import BaseModel, ValidationError

from boosty_downloader.src.infrastructure.boosty_api.models.post.posts_request import (
    SkippedPost,
)
from boosty_downloader.src.infrastructure.boosty_api.models.unknown_content import (
    UnknownContent,
)
from boosty_downloader.src.infrastructure.boosty_api.utils.validation_errors import (
    GITHUB_ISSUES_URL,
    format_run_summary,
    format_skipped_post,
    format_validation_errors,
)


class _Color(Enum):
    red = 'red'


class _Inner(BaseModel):
    type: _Color


class _Outer(BaseModel):
    data: list[_Inner]
    title: str


def _real_errors(payload: dict) -> list:
    with pytest.raises(ValidationError) as exc_info:
        _Outer.model_validate(payload)
    return exc_info.value.errors()


def test_enum_error_shows_the_offending_word():
    lines = format_validation_errors(
        _real_errors({'data': [{'type': 'imaginary_dash'}], 'title': 't'})
    )

    assert lines == ["data[0].type: unknown value 'imaginary_dash'"]


def test_non_enum_error_keeps_pydantic_message():
    lines = format_validation_errors(_real_errors({'data': []}))

    assert lines == ['title: Field required']


def test_nested_loc_renders_as_api_path():
    lines = format_validation_errors(
        _real_errors({'data': [{'type': 'red'}, {'type': 'nope'}], 'title': 't'})
    )

    assert lines == ["data[1].type: unknown value 'nope'"]


def test_skipped_post_block_names_the_post_and_lists_problems():
    block = format_skipped_post(
        SkippedPost(
            post_id='b1',
            title='broken post',
            errors=_real_errors({'data': [{'type': 'nope'}], 'title': 't'}),
        )
    )

    assert 'broken post' in block
    assert 'b1' in block
    assert "data[0].type: unknown value 'nope'" in block


def test_run_summary_lists_everything_and_asks_to_report():
    summary = format_run_summary(
        [SkippedPost(post_id='b1', title='broken post', errors=[])],
        {UnknownContent(path='data[0].type', raw='novel_thing')},
    )

    assert summary is not None
    assert 'broken post' in summary
    assert "data[0].type = 'novel_thing'" in summary
    assert GITHUB_ISSUES_URL in summary


def test_run_summary_is_none_when_clean():
    assert format_run_summary([], set()) is None
