"""A pasted post link must yield the creator and the post id, or a clear error."""

from __future__ import annotations

import pytest

from boosty_downloader.infrastructure.boosty_api.utils.post_url import (
    InvalidPostUrlError,
    PostRef,
    parse_post_url,
)

POST_ID = '20000000-0000-4000-8000-000000000042'


@pytest.mark.parametrize(
    'url',
    [
        f'https://boosty.to/creator/posts/{POST_ID}',
        f'https://boosty.to/creator/posts/{POST_ID}/',
        f'https://boosty.to/creator/posts/{POST_ID}?share=post_page',
        f'https://www.boosty.to/creator/posts/{POST_ID}#comments',
    ],
    ids=['plain', 'trailing-slash', 'query', 'www-and-fragment'],
)
def test_post_links_as_users_paste_them(url: str) -> None:
    assert parse_post_url(url) == PostRef(author_name='creator', post_id=POST_ID)


@pytest.mark.parametrize(
    'url',
    [
        'https://boosty.to/creator',
        'https://boosty.to/creator/posts',
        f'https://boosty.to/creator/media/{POST_ID}',
        f'https://patreon.com/creator/posts/{POST_ID}',
        f'boosty.to/creator/posts/{POST_ID}',
        'not a url',
    ],
    ids=['blog-page', 'no-id', 'not-a-post-path', 'other-site', 'no-scheme', 'garbage'],
)
def test_anything_else_is_rejected_with_the_expected_shape(url: str) -> None:
    """The old parser took the wrong path segment silently; now the user gets told."""
    with pytest.raises(InvalidPostUrlError) as info:
        parse_post_url(url)

    assert 'boosty.to/<creator>/posts/<post id>' in str(info.value)
