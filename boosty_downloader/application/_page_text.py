"""Build paragraph, heading and list presentation from stored post text."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from boosty_downloader.application.mappers.html_converter import (
    convert_list_style,
    convert_text_fragment,
)
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import LineBreak, ParagraphBreak, TextBlock
from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenHeading,
    HtmlGenList,
    HtmlGenParagraph,
    HtmlInline,
    HtmlLineBreak,
    HtmlListItem,
    HtmlTextBlock,
    HtmlTextFragment,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from boosty_downloader.application.ports import LinkUrl
    from boosty_downloader.domain.stored_post import ListBlock, ListItem, TextContent


@dataclass
class _TextFlow:
    """Collect adjacent fragments into one paragraph or heading."""

    blocks: list[HtmlTextBlock] = field(default_factory=list[HtmlTextBlock])
    fragments: list[HtmlInline] = field(default_factory=list[HtmlInline])
    heading_level: int = 0

    def append(self, fragment: HtmlInline, heading_level: int) -> None:
        if self.fragments and heading_level != self.heading_level:
            self.flush()
        self.heading_level = heading_level
        self.fragments.append(fragment)

    def flush(self) -> None:
        if self.heading_level:
            self.blocks.append(HtmlGenHeading(self.heading_level, self.fragments))
        else:
            self.blocks.append(HtmlGenParagraph(self.fragments))
        self.fragments = []
        self.heading_level = 0


def build_text_blocks(
    content: Iterable[TextContent], *, link_url: LinkUrl | None = None
) -> list[HtmlTextBlock]:
    """Join adjacent text blocks; only explicit boundaries retain empty paragraphs."""
    flow = _TextFlow()
    for block in content:
        match block:
            case ParagraphBreak():
                flow.flush()
            case TextBlock():
                _append_text_block(flow, block, link_url)
    if flow.fragments:
        flow.flush()
    return flow.blocks


def _append_text_block(
    flow: _TextFlow, block: TextBlock, link_url: LinkUrl | None
) -> None:
    level = _leading_level(block, flow.heading_level)
    for fragment in block.fragments:
        match fragment:
            case LineBreak():
                flow.append(HtmlLineBreak(), level)
            case PostDataChunkText.TextFragment():
                if not fragment.text:
                    continue
                level = fragment.header_level
                flow.append(_build_text_fragment(fragment, link_url), level)


def _build_text_fragment(
    fragment: PostDataChunkText.TextFragment, link_url: LinkUrl | None
) -> HtmlTextFragment:
    presentation = convert_text_fragment(fragment)
    if link_url is not None and presentation.link_url is not None:
        presentation.link_url = link_url(presentation.link_url)
    return presentation


def _leading_level(block: TextBlock, fallback: int) -> int:
    """Leading breaks belong to the text they precede within this block."""
    for fragment in block.fragments:
        if isinstance(fragment, PostDataChunkText.TextFragment) and fragment.text:
            return fragment.header_level
    return fallback


def build_textual_list(
    block: ListBlock, *, link_url: LinkUrl | None = None
) -> HtmlGenList:
    """Keep stored paragraphs and nested items inside their ordered or unordered list."""
    return HtmlGenList(
        items=[_build_list_item(item, link_url) for item in block.items],
        style=convert_list_style(block.style),
    )


def _build_list_item(item: ListItem, link_url: LinkUrl | None) -> HtmlListItem:
    return HtmlListItem(
        data=[*build_text_blocks(item.data, link_url=link_url)],
        nested_items=[
            _build_list_item(nested, link_url) for nested in item.nested_items
        ],
    )
