"""The saved body format preserves ordered content and rejects ambiguous values."""

from copy import deepcopy
from json import loads

import pytest
from pydantic import TypeAdapter, ValidationError

from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.domain.stored_post import (
    Block,
    LineBreak,
    ListBlock,
    ListItem,
    MediaBlock,
    ParagraphBreak,
    TextBlock,
)
from boosty_downloader.infrastructure.library._post_json_blocks import (
    JsonBlock,
    decode_blocks,
    encode_blocks,
)

TextFragment = PostDataChunkText.TextFragment
TextStyle = TextFragment.TextStyle
ListStyle = PostDataChunkTextualList.ListStyle
BODY_ADAPTER = TypeAdapter[list[JsonBlock]](list[JsonBlock])

GOLDEN_BODY = r"""
[
  {
    "type": "text",
    "fragments": [
      {
        "type": "text",
        "text": "Привет 🚀 <br> __PARAGRAPH_BREAK__\n",
        "link_url": "https://example.com/урок?q=1&n=2",
        "header_level": 6,
        "style": {"bold": true, "italic": true, "underline": true}
      },
      {"type": "br"},
      {
        "type": "text",
        "text": "",
        "link_url": null,
        "header_level": 0,
        "style": {"bold": false, "italic": false, "underline": false}
      }
    ]
  },
  {"type": "paragraph_break"},
  {"type": "paragraph_break"},
  {
    "type": "list",
    "style": "ordered",
    "items": [
      {
        "data": [{"type": "text", "fragments": []}, {"type": "paragraph_break"}],
        "nested_items": [
          {
            "data": [
              {
                "type": "text",
                "fragments": [
                  {"type": "br"},
                  {
                    "type": "text",
                    "text": "Вложенный пункт",
                    "link_url": null,
                    "header_level": 0,
                    "style": {"bold": false, "italic": false, "underline": true}
                  }
                ]
              }
            ],
            "nested_items": [{"data": [], "nested_items": []}]
          }
        ]
      },
      {"data": [], "nested_items": []}
    ]
  },
  {"type": "media", "media_id": "image:one"},
  {"type": "media", "media_id": "file:two"},
  {"type": "media", "media_id": "image:one"},
  {"type": "list", "style": "unordered", "items": []},
  {"type": "text", "fragments": []}
]
"""


@pytest.fixture
def body() -> list[Block]:
    nested = ListItem(
        [
            TextBlock(
                [
                    LineBreak(),
                    TextFragment('Вложенный пункт', style=TextStyle(underline=True)),
                ]
            )
        ],
        [ListItem([])],
    )
    return [
        TextBlock(
            [
                TextFragment(
                    'Привет 🚀 <br> __PARAGRAPH_BREAK__\n',
                    link_url='https://example.com/урок?q=1&n=2',
                    header_level=6,
                    style=TextStyle(bold=True, italic=True, underline=True),
                ),
                LineBreak(),
                TextFragment(''),
            ]
        ),
        ParagraphBreak(),
        ParagraphBreak(),
        ListBlock(
            [ListItem([TextBlock([]), ParagraphBreak()], [nested]), ListItem([])],
            ListStyle.ordered,
        ),
        MediaBlock('image:one'),
        MediaBlock('file:two'),
        MediaBlock('image:one'),
        ListBlock([]),
        TextBlock([]),
    ]


def _mutate_body(body: list[Block]) -> None:
    text, _, _, listing, *_ = body
    assert isinstance(text, TextBlock)
    fragment = text.fragments[0]
    assert isinstance(fragment, TextFragment)
    fragment.style.bold = False
    text.fragments.clear()
    assert isinstance(listing, ListBlock)
    nested = listing.items[0].nested_items[0]
    nested_text = nested.data[0]
    assert isinstance(nested_text, TextBlock)
    nested_fragment = nested_text.fragments[1]
    assert isinstance(nested_fragment, TextFragment)
    nested_fragment.style.underline = False
    nested.nested_items.clear()
    listing.items.clear()
    body.clear()


def test_encoding_matches_the_explicit_json_format(body: list[Block]) -> None:
    encoded = BODY_ADAPTER.dump_json(encode_blocks(body))

    assert loads(encoded) == loads(GOLDEN_BODY)


def test_decoding_explicit_json_preserves_the_complete_body(body: list[Block]) -> None:
    encoded = BODY_ADAPTER.validate_json(GOLDEN_BODY)

    assert decode_blocks(encoded) == body


def test_round_trip_retains_body_order_and_does_not_change_input(
    body: list[Block],
) -> None:
    expected = deepcopy(body)

    encoded = BODY_ADAPTER.dump_json(encode_blocks(body))
    restored = decode_blocks(BODY_ADAPTER.validate_json(encoded))

    assert restored == expected
    assert body == expected


def test_empty_body_is_valid() -> None:
    assert BODY_ADAPTER.dump_json(encode_blocks([])) == b'[]'
    assert decode_blocks(BODY_ADAPTER.validate_json('[]')) == []


def test_omitted_optional_fields_use_domain_defaults() -> None:
    encoded = BODY_ADAPTER.validate_json(
        '[{"type":"text","fragments":[{"type":"text","text":""}]},'
        '{"type":"list","items":[{"data":[]}]}]'
    )

    assert decode_blocks(encoded) == [
        TextBlock([TextFragment('')]),
        ListBlock([ListItem([])]),
    ]


def test_encoded_values_own_their_styles_and_nested_collections(
    body: list[Block],
) -> None:
    encoded = encode_blocks(body)

    _mutate_body(body)

    assert loads(BODY_ADAPTER.dump_json(encoded)) == loads(GOLDEN_BODY)


def test_decoded_snapshots_own_their_styles_and_nested_collections(
    body: list[Block],
) -> None:
    encoded = BODY_ADAPTER.validate_json(GOLDEN_BODY)
    first = decode_blocks(encoded)
    second = decode_blocks(encoded)

    _mutate_body(first)

    assert second == body
    assert loads(BODY_ADAPTER.dump_json(encoded)) == loads(GOLDEN_BODY)


@pytest.mark.parametrize(
    'document',
    [
        pytest.param('[{}]', id='missing-body-tag'),
        pytest.param('[{"type":"unknown"}]', id='unknown-body-tag'),
        pytest.param('[{"type":"text","fragments":[{}]}]', id='missing-fragment-tag'),
        pytest.param(
            '[{"type":"text","fragments":[{"type":"paragraph_break"}]}]',
            id='invalid-fragment-tag',
        ),
        pytest.param(
            '[{"type":"list","items":[{"data":[{"type":"media","media_id":"file:x"}]}]}]',
            id='media-inside-list-item',
        ),
        pytest.param(
            '[{"type":"list","items":[{"data":[{"type":"list","items":[]}]}]}]',
            id='list-block-inside-list-item',
        ),
        pytest.param(
            '[{"type":"paragraph_break","text":"lost"}]', id='extra-block-key'
        ),
        pytest.param(
            '[{"type":"text","fragments":[{"type":"br","text":"lost"}]}]',
            id='extra-fragment-key',
        ),
        pytest.param(
            '[{"type":"text","fragments":[{"type":"text","text":"x","style":{"color":"red"}}]}]',
            id='extra-style-key',
        ),
        pytest.param('[{"type":"media","media_id":42}]', id='non-string-media-id'),
        pytest.param('[{"type":"text","fragments":{}}]', id='non-array-fragments'),
        pytest.param(
            '[{"type":"text","fragments":[{"type":"text","text":42}]}]',
            id='non-string-text',
        ),
        pytest.param(
            '[{"type":"text","fragments":[{"type":"text","text":"x","style":{"bold":1}}]}]',
            id='non-boolean-style',
        ),
        pytest.param(
            '[{"type":"text","fragments":[{"type":"text","text":"x","header_level":true}]}]',
            id='boolean-heading-level',
        ),
        pytest.param(
            '[{"type":"text","fragments":[{"type":"text","text":"x","header_level":-1}]}]',
            id='negative-heading-level',
        ),
        pytest.param(
            '[{"type":"text","fragments":[{"type":"text","text":"x","header_level":7}]}]',
            id='heading-level-over-six',
        ),
        pytest.param(
            '[{"type":"list","items":[],"style":"bullets"}]', id='unknown-list-style'
        ),
    ],
)
def test_invalid_body_values_are_rejected(document: str) -> None:
    with pytest.raises(ValidationError):
        BODY_ADAPTER.validate_json(document)


def test_encoding_revalidates_mutated_domain_values() -> None:
    fragment = TextFragment('heading')
    fragment.header_level = 7

    with pytest.raises(ValidationError):
        encode_blocks([TextBlock([fragment])])
