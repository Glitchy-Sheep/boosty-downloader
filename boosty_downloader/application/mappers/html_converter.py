"""Converters from domain models to HTML generator models."""

from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenAudio,
    HtmlGenList,
    HtmlGenText,
    HtmlGenVideo,
    HtmlListItem,
    HtmlListStyle,
    HtmlTextFragment,
    HtmlTextStyle,
)


def convert_text_to_html(chunk: PostDataChunkText) -> HtmlGenText:
    """Convert domain text chunk to HTML text model."""
    fragments: list[HtmlTextFragment] = []
    for frag in chunk.text_fragments:
        style = HtmlTextStyle(
            bold=frag.style.bold,
            italic=frag.style.italic,
            underline=frag.style.underline,
        )
        html_fragment = HtmlTextFragment(
            text=frag.text,
            link_url=frag.link_url,
            header_level=frag.header_level,
            style=style,
        )
        fragments.append(html_fragment)

    return HtmlGenText(text_fragments=fragments)


def convert_video_to_html(src: str, title: str) -> HtmlGenVideo:
    """Convert domain video chunk to HTML video model."""
    return HtmlGenVideo(url=src, title=title)


def convert_list_to_html(chunk: PostDataChunkTextualList) -> HtmlGenList:
    """Convert domain list chunk to HTML list model."""

    def convert_list_item(item: PostDataChunkTextualList.ListItem) -> HtmlListItem:
        data = [convert_text_to_html(text_chunk) for text_chunk in item.data]
        nested_items = [convert_list_item(nested) for nested in item.nested_items]
        return HtmlListItem(data=data, nested_items=nested_items)

    items = [convert_list_item(item) for item in chunk.items]
    style = (
        HtmlListStyle.ORDERED
        if chunk.style is PostDataChunkTextualList.ListStyle.ordered
        else HtmlListStyle.UNORDERED
    )

    return HtmlGenList(items=items, style=style)


def convert_audio_to_html(src: str, title: str) -> HtmlGenAudio:
    """Convert audio source to HTML audio model."""
    return HtmlGenAudio(url=src, title=title)
