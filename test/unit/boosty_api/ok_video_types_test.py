"""Regression tests for tolerant parsing of Boosty ok_video url types."""

from __future__ import annotations

import pytest

from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
    BoostyOkVideoUrl,
)
from boosty_downloader.src.infrastructure.boosty_api.models.unknown_value import (
    BoostyUnknownValue,
)


@pytest.mark.parametrize('new_type', ['imaginary_dash', 'imaginary_hls'])
def test_unknown_url_type_keeps_raw_word(new_type: str):
    url = BoostyOkVideoUrl.model_validate(
        {'url': 'https://vd.example/1', 'type': new_type}
    )

    assert url.type == BoostyUnknownValue(raw=new_type)


@pytest.mark.parametrize('ondemand_type', ['ondemand_dash', 'ondemand_hls'])
def test_ondemand_types_parse_into_the_enum(ondemand_type: str):
    """The Aug 2026 additions must not fire the report-to-github warning."""
    url = BoostyOkVideoUrl.model_validate({'url': '', 'type': ondemand_type})

    assert url.type is BoostyOkVideoType(ondemand_type)


def test_known_url_type_still_parses_exactly():
    url = BoostyOkVideoUrl.model_validate(
        {'url': 'https://vd.example/1', 'type': 'medium'}
    )

    assert url.type is BoostyOkVideoType.medium
