"""What the listing tells about a post is optional: broken or absent, it never fails the post."""

from __future__ import annotations

import pytest

from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO

_BARE_POST: dict[str, object] = {
    'id': 'p1',
    'title': 't',
    'createdAt': 1750000000,
    'updatedAt': 1750000000,
    'hasAccess': True,
    'signedQuery': '',
    'data': [],
}
_FIELDS = ('publish_time', 'tags', 'teaser', 'content_counters', 'count')


@pytest.mark.parametrize(
    'overview',
    [
        pytest.param({}, id='fields-absent'),
        pytest.param(
            dict.fromkeys(
                ('publishTime', 'tags', 'teaser', 'contentCounters', 'count'), None
            ),
            id='fields-null',
        ),
        pytest.param(
            {
                'publishTime': 'soon',
                'tags': [{'id': 1}],
                'teaser': [{'type': 'image', 'url': 'u'}],
                'contentCounters': 'many',
                'count': {'likes': 'lots'},
            },
            id='fields-malformed',
        ),
    ],
)
def test_missing_or_broken_overview_leaves_the_post_whole(overview: dict[str, object]):
    post = PostDTO.model_validate({**_BARE_POST, **overview})

    assert [getattr(post, name) for name in _FIELDS] == [None] * len(_FIELDS)
