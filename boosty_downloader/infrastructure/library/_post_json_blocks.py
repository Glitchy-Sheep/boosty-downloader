"""Tagged JSON values preserve body structure independently of domain models."""

from collections.abc import Sequence
from copy import deepcopy
from enum import Enum
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field

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
    TextContent,
)

TextFragment = PostDataChunkText.TextFragment
TextStyle = TextFragment.TextStyle
ListStyle = PostDataChunkTextualList.ListStyle


class JsonBlockType(str, Enum):
    """Discriminators for saved body blocks."""

    text = 'text'
    paragraph_break = 'paragraph_break'
    list = 'list'
    media = 'media'


class JsonFragmentType(str, Enum):
    """Discriminators for inline text and explicit line breaks."""

    text = 'text'
    br = 'br'


class _JsonValue(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
        strict=True,
        revalidate_instances='always',
    )


class JsonTextFragment(_JsonValue):
    """Text and its complete inline formatting."""

    type: Literal[JsonFragmentType.text] = JsonFragmentType.text
    text: str
    link_url: str | None = None
    header_level: int = Field(default=0, ge=0, le=6)
    style: TextStyle = Field(default_factory=TextStyle)


class JsonLineBreak(_JsonValue):
    """An explicit line break, distinguishable from an empty text fragment."""

    type: Literal[JsonFragmentType.br] = JsonFragmentType.br


JsonFragment: TypeAlias = Annotated[
    JsonTextFragment | JsonLineBreak, Field(discriminator='type')
]


class JsonTextBlock(_JsonValue):
    """An ordered run of text fragments and inline breaks."""

    type: Literal[JsonBlockType.text] = JsonBlockType.text
    fragments: list[JsonFragment]


class JsonParagraphBreak(_JsonValue):
    """A paragraph boundary, including consecutive empty paragraphs."""

    type: Literal[JsonBlockType.paragraph_break] = JsonBlockType.paragraph_break


JsonTextContent: TypeAlias = Annotated[
    JsonTextBlock | JsonParagraphBreak, Field(discriminator='type')
]


class JsonListItem(_JsonValue):
    """List item text and its nested items."""

    data: list[JsonTextContent]
    nested_items: list['JsonListItem'] = Field(default_factory=list['JsonListItem'])


class JsonListBlock(_JsonValue):
    """A list whose style applies to all nesting levels."""

    type: Literal[JsonBlockType.list] = JsonBlockType.list
    items: list[JsonListItem]
    style: ListStyle = ListStyle.unordered


class JsonMediaBlock(_JsonValue):
    """A reference to the owning record's media inventory."""

    type: Literal[JsonBlockType.media] = JsonBlockType.media
    media_id: str = Field(min_length=1)


JsonBlock: TypeAlias = Annotated[
    JsonTextBlock | JsonParagraphBreak | JsonListBlock | JsonMediaBlock,
    Field(discriminator='type'),
]


def encode_blocks(blocks: Sequence[Block]) -> list[JsonBlock]:
    """Validate and copy domain content into tagged JSON values."""
    return [_encode_block(block) for block in blocks]


def decode_blocks(blocks: Sequence[JsonBlock]) -> list[Block]:
    """Restore an independent domain body from validated JSON values."""
    return [_decode_block(block) for block in blocks]


def _encode_block(block: Block) -> JsonBlock:
    match block:
        case TextBlock() | ParagraphBreak():
            return _encode_text_content(block)
        case ListBlock():
            return JsonListBlock(
                items=[_encode_list_item(item) for item in block.items],
                style=block.style,
            )
        case MediaBlock():
            return JsonMediaBlock(media_id=block.media_id)


def _encode_text_content(block: TextContent) -> JsonTextContent:
    match block:
        case TextBlock():
            return JsonTextBlock(
                fragments=[_encode_fragment(fragment) for fragment in block.fragments]
            )
        case ParagraphBreak():
            return JsonParagraphBreak()


def _encode_fragment(fragment: TextFragment | LineBreak) -> JsonFragment:
    match fragment:
        case TextFragment():
            return JsonTextFragment(
                text=fragment.text,
                link_url=fragment.link_url,
                header_level=fragment.header_level,
                style=fragment.style,
            )
        case LineBreak():
            return JsonLineBreak()


def _encode_list_item(item: ListItem) -> JsonListItem:
    return JsonListItem(
        data=[_encode_text_content(block) for block in item.data],
        nested_items=[_encode_list_item(nested) for nested in item.nested_items],
    )


def _decode_block(block: JsonBlock) -> Block:
    match block:
        case JsonTextBlock() | JsonParagraphBreak():
            return _decode_text_content(block)
        case JsonListBlock():
            return ListBlock(
                items=[_decode_list_item(item) for item in block.items],
                style=block.style,
            )
        case JsonMediaBlock():
            return MediaBlock(media_id=block.media_id)


def _decode_text_content(block: JsonTextContent) -> TextContent:
    match block:
        case JsonTextBlock():
            return TextBlock(
                fragments=[_decode_fragment(fragment) for fragment in block.fragments]
            )
        case JsonParagraphBreak():
            return ParagraphBreak()


def _decode_fragment(fragment: JsonFragment) -> TextFragment | LineBreak:
    match fragment:
        case JsonTextFragment():
            return TextFragment(
                text=fragment.text,
                link_url=fragment.link_url,
                header_level=fragment.header_level,
                style=deepcopy(fragment.style),
            )
        case JsonLineBreak():
            return LineBreak()


def _decode_list_item(item: JsonListItem) -> ListItem:
    return ListItem(
        data=[_decode_text_content(block) for block in item.data],
        nested_items=[_decode_list_item(nested) for nested in item.nested_items],
    )
