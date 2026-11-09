"""Blog descriptions retain all supported text without media or rich markup."""

import json
from datetime import datetime, timezone

import pytest
from support.synthetic_blog import (
    BLOG_TITLE,
    DESCRIPTION_TEXT,
    OWNER_NAME,
    POST_COUNT,
    synthetic_blog,
)
from support.synthetic_post import block_end, image_chunk, text_chunk

from boosty_downloader.application.mappers.blog_info import map_blog_info
from boosty_downloader.domain.stored_post import AuthorInfo
from boosty_downloader.infrastructure.boosty_api.models.blog import BlogInfoDTO

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
AUTHOR = 'fixture-author'


def test_complete_blog_maps_metadata_without_remote_image_paths() -> None:
    dto = BlogInfoDTO.model_validate(synthetic_blog())
    before = dto.model_copy(deep=True)

    assert map_blog_info(dto, AUTHOR, NOW) == AuthorInfo(
        author=AUTHOR,
        synced_at=NOW,
        title=BLOG_TITLE,
        owner_name=OWNER_NAME,
        description=DESCRIPTION_TEXT,
        remote_post_count=POST_COUNT,
    )
    assert dto == before


@pytest.mark.parametrize(
    'payload',
    [
        {},
        {'description': []},
        {'owner': None, 'count': None},
        {'title': {}, 'owner': [], 'count': 'unknown', 'description': 'unknown'},
    ],
)
def test_absent_or_malformed_optional_fields_are_not_invented(
    payload: dict[str, object],
) -> None:
    assert map_blog_info(
        BlogInfoDTO.model_validate(payload), AUTHOR, NOW
    ) == AuthorInfo(AUTHOR, NOW)


def test_styled_fragments_links_and_headers_preserve_full_text_and_paragraphs() -> None:
    long_text = 'Long description. ' * 100
    dto = BlogInfoDTO.model_validate(
        {
            'description': [
                {
                    'type': 'header',
                    'content': json.dumps(['Heading', 'header-two', []]),
                    'modificator': 'BLOCK_END',
                },
                text_chunk('First '),
                {
                    'type': 'link',
                    'content': json.dumps(['link', 'unstyled', [[0, 0, 4]]]),
                    'url': 'https://example.test',
                    'explicit': True,
                },
                text_chunk(' and line\r\nbreak.'),
                block_end(),
                image_chunk(),
                {'type': 'new-format', 'content': 'Ignored content'},
                {**text_chunk(long_text), 'modificator': 'BLOCK_END'},
                text_chunk('Final paragraph'),
            ],
        }
    )
    before = dto.model_copy(deep=True)

    result = map_blog_info(dto, AUTHOR, NOW)

    assert result.description == (
        'Heading\n\nFirst link and line\r\nbreak.\n\n'
        + long_text
        + '\n\nFinal paragraph'
    )
    assert dto == before


@pytest.mark.parametrize('style', ['ordered', 'unordered', 'future-style'])
def test_nested_lists_keep_item_order_and_boundaries_with_surrounding_prose(
    style: str,
) -> None:
    dto = BlogInfoDTO.model_validate(
        {
            'description': [
                text_chunk('Before'),
                block_end(),
                {
                    'type': 'list',
                    'style': style,
                    'items': [
                        {
                            'data': [text_chunk('Parent '), text_chunk('item')],
                            'items': [
                                {'data': [text_chunk('Child one')]},
                                {'data': [text_chunk('Child two')]},
                            ],
                        },
                        {
                            'data': [
                                {'type': 'future-type', 'content': 'Ignored'},
                                text_chunk('Second item'),
                            ],
                        },
                    ],
                },
                image_chunk(),
                text_chunk('After'),
            ],
        }
    )

    result = map_blog_info(dto, AUTHOR, NOW)

    assert result.description == (
        'Before\n\nParent item\nChild one\nChild two\nSecond item\n\nAfter'
    )


@pytest.mark.parametrize(
    'description', [[image_chunk()], [block_end()], [text_chunk('  ')]]
)
def test_description_without_visible_text_is_absent(
    description: list[dict[str, object]],
) -> None:
    dto = BlogInfoDTO.model_validate({'description': description})

    assert map_blog_info(dto, AUTHOR, NOW).description is None


@pytest.mark.parametrize(
    ('content', 'cause'),
    [
        ('[]', IndexError),
        ('{}', KeyError),
        ('[null, "unstyled", []]', TypeError),
        ('["text", "unstyled", null]', TypeError),
        ('["text", [], []]', TypeError),
    ],
    ids=['empty-array', 'object', 'null-text', 'null-styles', 'list-header-style'],
)
@pytest.mark.parametrize('nested', [False, True], ids=['text', 'nested-list'])
def test_malformed_text_rejects_the_complete_description_with_context(
    content: str, cause: type[Exception], *, nested: bool
) -> None:
    chunk: dict[str, object] = {**text_chunk(''), 'content': content}
    if nested:
        chunk = {
            'type': 'list',
            'items': [
                {
                    'data': [text_chunk('Parent')],
                    'items': [{'data': [chunk]}],
                },
            ],
        }
    dto = BlogInfoDTO.model_validate(
        {'description': [text_chunk('Before'), chunk, text_chunk('After')]}
    )
    before = dto.model_copy(deep=True)

    with pytest.raises(ValueError, match='Blog description') as raised:
        map_blog_info(dto, AUTHOR, NOW)

    assert isinstance(raised.value.__cause__, cause)
    assert dto == before
