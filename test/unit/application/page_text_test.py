"""Stored text keeps paragraph boundaries, heading runs and nested list content."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from support.synthetic_post import block_end, synthetic_post, text_chunk

from boosty_downloader.application._page_text import (
    build_text_blocks,
    build_textual_list,
)
from boosty_downloader.application.mappers.live_post import map_post_dto_to_live
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.domain.stored_post import (
    LineBreak,
    ListBlock,
    ListItem,
    ParagraphBreak,
    TextBlock,
    TextContent,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)
from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenHeading,
    HtmlGenList,
    HtmlGenParagraph,
    HtmlLineBreak,
    HtmlListItem,
    HtmlListStyle,
    HtmlTextFragment,
    HtmlTextStyle,
)

TextFragment = PostDataChunkText.TextFragment
TextStyle = TextFragment.TextStyle


def test_adjacent_text_blocks_preserve_split_words_and_author_whitespace():
    blocks = [
        TextBlock([TextFragment('down')]),
        TextBlock([TextFragment('loader', style=TextStyle(bold=True))]),
        TextBlock([TextFragment('  ready ')]),
    ]

    assert build_text_blocks(iter(blocks)) == [
        HtmlGenParagraph(
            [
                HtmlTextFragment('down'),
                HtmlTextFragment('loader', style=HtmlTextStyle(bold=True)),
                HtmlTextFragment('  ready '),
            ]
        )
    ]


@pytest.mark.parametrize(
    ('content', 'expected'),
    [
        ([], []),
        ([TextBlock([])], []),
        ([TextBlock([TextFragment('')])], []),
        ([TextBlock([TextFragment('', header_level=2)])], []),
        ([ParagraphBreak()], [HtmlGenParagraph([])]),
        (
            [ParagraphBreak(), TextBlock([]), ParagraphBreak()],
            [HtmlGenParagraph([]), HtmlGenParagraph([])],
        ),
        (
            [TextBlock([TextFragment('body')]), ParagraphBreak()],
            [HtmlGenParagraph([HtmlTextFragment('body')])],
        ),
        (
            [TextBlock([TextFragment('body')]), ParagraphBreak(), ParagraphBreak()],
            [HtmlGenParagraph([HtmlTextFragment('body')]), HtmlGenParagraph([])],
        ),
        (
            [ParagraphBreak(), TextBlock([TextFragment('body')])],
            [HtmlGenParagraph([]), HtmlGenParagraph([HtmlTextFragment('body')])],
        ),
        (
            [TextBlock([LineBreak()]), ParagraphBreak()],
            [HtmlGenParagraph([HtmlLineBreak()])],
        ),
    ],
    ids=[
        'no-content',
        'empty-block',
        'empty-fragment',
        'empty-heading-fragment',
        'single-blank-paragraph',
        'empty-block-keeps-boundaries',
        'closing-boundary-adds-no-blank',
        'repeated-boundary-keeps-blank',
        'leading-blank-paragraph',
        'inline-break-is-content',
    ],
)
def test_empty_text_and_explicit_paragraph_boundaries(
    content: list[TextContent], expected: list[HtmlGenParagraph | HtmlGenHeading]
):
    assert build_text_blocks(content) == expected


def test_empty_fragments_do_not_split_nonempty_text_or_change_heading_context():
    content = [
        TextBlock([TextFragment('before'), TextFragment('', header_level=3)]),
        TextBlock([TextFragment('after')]),
    ]

    assert build_text_blocks(content) == [
        HtmlGenParagraph([HtmlTextFragment('before'), HtmlTextFragment('after')])
    ]


def test_inline_breaks_retain_the_decorated_heading_across_text_blocks():
    content = [
        TextBlock([TextFragment('Read ', header_level=2, style=TextStyle(bold=True))]),
        TextBlock([LineBreak()]),
        TextBlock(
            [
                TextFragment(
                    'this',
                    link_url='https://example.com/?first=1&next=2',
                    header_level=2,
                    style=TextStyle(italic=True, underline=True),
                ),
                LineBreak(),
            ]
        ),
        ParagraphBreak(),
        ParagraphBreak(),
        TextBlock([TextFragment('Body')]),
    ]

    assert build_text_blocks(content) == [
        HtmlGenHeading(
            level=2,
            fragments=[
                HtmlTextFragment(
                    'Read ', header_level=2, style=HtmlTextStyle(bold=True)
                ),
                HtmlLineBreak(),
                HtmlTextFragment(
                    'this',
                    link_url='https://example.com/?first=1&next=2',
                    header_level=2,
                    style=HtmlTextStyle(italic=True, underline=True),
                ),
                HtmlLineBreak(),
            ],
        ),
        HtmlGenParagraph([]),
        HtmlGenParagraph([HtmlTextFragment('Body')]),
    ]


def test_heading_level_changes_separate_blocks_without_extra_empty_paragraphs():
    content = [
        TextBlock(
            [
                TextFragment('intro'),
                TextFragment('title', header_level=1),
                TextFragment('subtitle', header_level=2),
                TextFragment('body'),
            ]
        )
    ]

    assert build_text_blocks(content) == [
        HtmlGenParagraph([HtmlTextFragment('intro')]),
        HtmlGenHeading(1, [HtmlTextFragment('title', header_level=1)]),
        HtmlGenHeading(2, [HtmlTextFragment('subtitle', header_level=2)]),
        HtmlGenParagraph([HtmlTextFragment('body')]),
    ]


def test_leading_inline_break_inherits_the_heading_in_its_text_block():
    content = [TextBlock([LineBreak(), TextFragment('title', header_level=2)])]

    assert build_text_blocks(content) == [
        HtmlGenHeading(2, [HtmlLineBreak(), HtmlTextFragment('title', header_level=2)]),
    ]


def test_leading_break_in_a_new_paragraph_does_not_extend_the_previous_heading():
    content = [
        TextBlock([TextFragment('title', header_level=2)]),
        TextBlock([LineBreak(), TextFragment('body')]),
    ]

    assert build_text_blocks(content) == [
        HtmlGenHeading(2, [HtmlTextFragment('title', header_level=2)]),
        HtmlGenParagraph([HtmlLineBreak(), HtmlTextFragment('body')]),
    ]


def test_author_text_and_links_reach_the_renderer_without_escaping_or_markers():
    text = '<NEW_LINE_SYMBOL> <b>literal</b> & "quoted"'
    link = 'https://example.com/?value=%25&label="quoted"'

    assert build_text_blocks([TextBlock([TextFragment(text, link_url=link)])]) == [
        HtmlGenParagraph([HtmlTextFragment(text, link_url=link)])
    ]


@pytest.mark.parametrize(
    ('stored_style', 'html_style'),
    [
        (PostDataChunkTextualList.ListStyle.ordered, HtmlListStyle.ORDERED),
        (PostDataChunkTextualList.ListStyle.unordered, HtmlListStyle.UNORDERED),
    ],
    ids=['ordered', 'unordered'],
)
def test_list_items_use_the_same_paragraph_rules_at_every_depth(
    stored_style: PostDataChunkTextualList.ListStyle, html_style: HtmlListStyle
):
    nested = ListItem(data=[TextBlock([TextFragment('child'), LineBreak()])])
    block = ListBlock(
        style=stored_style,
        items=[
            ListItem(
                data=[
                    TextBlock([TextFragment('par')]),
                    TextBlock([TextFragment('ent')]),
                ],
                nested_items=[
                    ListItem(
                        data=[ParagraphBreak(), ParagraphBreak()],
                        nested_items=[nested],
                    )
                ],
            ),
            ListItem(data=[]),
        ],
    )

    assert build_textual_list(block) == HtmlGenList(
        style=html_style,
        items=[
            HtmlListItem(
                data=[
                    HtmlGenParagraph([HtmlTextFragment('par'), HtmlTextFragment('ent')])
                ],
                nested_items=[
                    HtmlListItem(
                        data=[HtmlGenParagraph([]), HtmlGenParagraph([])],
                        nested_items=[
                            HtmlListItem(
                                data=[
                                    HtmlGenParagraph(
                                        [HtmlTextFragment('child'), HtmlLineBreak()]
                                    )
                                ]
                            )
                        ],
                    )
                ],
            ),
            HtmlListItem(data=[]),
        ],
    )


def test_output_fragments_and_styles_are_independent_of_input_and_other_calls():
    shared_style = TextStyle(bold=True, italic=True, underline=True)
    fragments: list[TextFragment | LineBreak] = [
        TextFragment('first', style=shared_style),
        TextFragment('second', style=shared_style),
    ]
    content = [TextBlock(fragments)]
    original = deepcopy(content)
    first = build_text_blocks(content)
    second = build_text_blocks(content)
    expected_second = deepcopy(second)
    first_fragment = first[0].fragments[0]
    sibling_fragment = first[0].fragments[1]
    assert isinstance(first_fragment, HtmlTextFragment)
    assert isinstance(sibling_fragment, HtmlTextFragment)

    first_fragment.text = 'edited'
    first_fragment.style.bold = False
    first[0].fragments.append(HtmlLineBreak())

    assert sibling_fragment.style.bold
    assert content == original
    assert second == expected_second


def test_nested_list_output_owns_its_items_data_and_styles():
    fragment = TextFragment('child', style=TextStyle(underline=True))
    nested = ListItem(data=[TextBlock([fragment])])
    block = ListBlock(items=[ListItem(data=[], nested_items=[nested])])
    original = deepcopy(block)
    first = build_textual_list(block)
    second = build_textual_list(block)
    expected_second = deepcopy(second)
    child = first.items[0].nested_items[0]
    paragraph = child.data[0]
    assert isinstance(paragraph, HtmlGenParagraph)
    html_fragment = paragraph.fragments[0]
    assert isinstance(html_fragment, HtmlTextFragment)

    html_fragment.style.underline = False
    paragraph.fragments.clear()
    child.data.clear()
    first.items[0].nested_items.clear()

    assert block == original
    assert second == expected_second


def test_full_mapper_paragraph_and_inline_boundaries_survive_list_projection():
    chunks = [
        text_chunk('split'),
        text_chunk('word\r\nnext'),
        block_end(),
        block_end(),
        {
            'type': 'text',
            'content': json.dumps(['Heading\ncontinued', 'header-two', [[0, 0, 17]]]),
            'modificator': 'BLOCK_END',
        },
    ]
    payload = {
        **synthetic_post(),
        'data': [
            {'type': 'list', 'items': [{'data': [], 'items': [{'data': chunks}]}]}
        ],
    }
    live = map_post_dto_to_live(
        PostDTO.model_validate(payload), 'fixture-author', BoostyOkVideoType.medium
    )
    block = live.blocks[0]
    assert isinstance(block, ListBlock)
    child = build_textual_list(block).items[0].nested_items[0]

    assert child.data == [
        HtmlGenParagraph(
            [
                HtmlTextFragment('split'),
                HtmlTextFragment('word'),
                HtmlLineBreak(),
                HtmlTextFragment('next'),
            ]
        ),
        HtmlGenParagraph([]),
        HtmlGenHeading(
            2,
            [
                HtmlTextFragment(
                    'Heading', header_level=2, style=HtmlTextStyle(bold=True)
                ),
                HtmlLineBreak(),
                HtmlTextFragment(
                    'continued', header_level=2, style=HtmlTextStyle(bold=True)
                ),
            ],
        ),
    ]
