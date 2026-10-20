"""Whole-name matching for the download tag exclusions."""

from __future__ import annotations

import pytest

from boosty_downloader.application.filtering import has_excluded_tag


@pytest.mark.parametrize(
    ('tags', 'excluded', 'matches'),
    [
        (['sample'], ('SAMPLE',), True),
        ([' sample tag '], ('sample tag',), True),
        (['sample'], ('other', ' sample '), True),
        (['other', 'sample'], ('sample',), True),
        (['sample extended'], ('sample',), False),
        (['sample'], (), False),
        ([], ('sample',), False),
    ],
)
def test_tag_names_match_in_full(
    tags: list[str], excluded: tuple[str, ...], *, matches: bool
) -> None:
    assert has_excluded_tag(tags, excluded) is matches
