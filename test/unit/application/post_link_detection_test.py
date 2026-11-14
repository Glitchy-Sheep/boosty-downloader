"""Only authored Boosty post links require a cached page refresh."""

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from boosty_downloader.application.post_links import has_post_links
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    Block,
    LineBreak,
    ListBlock,
    ListItem,
    MediaBlock,
    ParagraphBreak,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)

_HREF = 'https://boosty.to/writer/posts/target'
_LINK = TextBlock([PostDataChunkText.TextFragment('Next post', link_url=_HREF)])


@pytest.mark.parametrize(
    ('blocks', 'expected'),
    [
        ([], False),
        ([TextBlock([PostDataChunkText.TextFragment(_HREF)])], False),
        ([ParagraphBreak(), MediaBlock('attachment')], False),
        ([TextBlock([LineBreak()]), _LINK], True),
        ([ListBlock([ListItem([_LINK])])], True),
        ([ListBlock([ListItem([], [ListItem([], [ListItem([_LINK])])])])], True),
        (
            [
                TextBlock(
                    [
                        PostDataChunkText.TextFragment(
                            'Other', link_url='https://example.com'
                        )
                    ]
                )
            ],
            False,
        ),
        (
            [
                TextBlock(
                    [
                        PostDataChunkText.TextFragment(
                            'Unsafe', link_url='javascript:' + _HREF
                        )
                    ]
                )
            ],
            False,
        ),
    ],
)
def test_cached_refresh_depends_on_authored_post_links(
    blocks: list[Block], *, expected: bool
) -> None:
    now = datetime(2026, 11, 14, tzinfo=timezone.utc)
    record = StoredPost(
        PostMetadata('source', 'writer', _HREF, 'Source', now, now),
        PostSync(now, now),
        blocks,
    )
    before = deepcopy(record)

    assert has_post_links(record) is expected
    assert record == before
