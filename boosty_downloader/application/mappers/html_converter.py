"""Converters from domain models to HTML generator models."""

from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenAudio,
    HtmlGenFile,
    HtmlGenList,
    HtmlGenText,
    HtmlGenVideo,
    HtmlListItem,
    HtmlListStyle,
    HtmlTextBlock,
    HtmlTextFragment,
    HtmlTextStyle,
)


def convert_text_to_html(chunk: PostDataChunkText) -> HtmlGenText:
    """Convert domain text chunk to HTML text model."""
    return HtmlGenText(
        text_fragments=[convert_text_fragment(frag) for frag in chunk.text_fragments]
    )


def convert_text_fragment(
    fragment: PostDataChunkText.TextFragment,
) -> HtmlTextFragment:
    """Copy styled text into an independent presentation fragment."""
    return HtmlTextFragment(
        text=fragment.text,
        link_url=fragment.link_url,
        header_level=fragment.header_level,
        style=HtmlTextStyle(
            bold=fragment.style.bold,
            italic=fragment.style.italic,
            underline=fragment.style.underline,
        ),
    )


def convert_video_to_html(src: str, title: str) -> HtmlGenVideo:
    """Convert domain video chunk to HTML video model."""
    return HtmlGenVideo(url=src, title=title)


def convert_list_to_html(chunk: PostDataChunkTextualList) -> HtmlGenList:
    """Convert domain list chunk to HTML list model."""

    def convert_list_item(item: PostDataChunkTextualList.ListItem) -> HtmlListItem:
        data: list[HtmlGenText | HtmlTextBlock] = [
            convert_text_to_html(text_chunk) for text_chunk in item.data
        ]
        nested_items = [convert_list_item(nested) for nested in item.nested_items]
        return HtmlListItem(data=data, nested_items=nested_items)

    items = [convert_list_item(item) for item in chunk.items]
    return HtmlGenList(items=items, style=convert_list_style(chunk.style))


def convert_list_style(style: PostDataChunkTextualList.ListStyle) -> HtmlListStyle:
    """Map the stored list style to its presentation counterpart."""
    match style:
        case PostDataChunkTextualList.ListStyle.ordered:
            return HtmlListStyle.ORDERED
        case PostDataChunkTextualList.ListStyle.unordered:
            return HtmlListStyle.UNORDERED


def convert_audio_to_html(src: str, title: str) -> HtmlGenAudio:
    """Convert audio source to HTML audio model."""
    return HtmlGenAudio(url=src, title=title)


def convert_file_to_html(src: str, filename: str, size: int | None) -> HtmlGenFile:
    """Convert a saved attachment to HTML file model: a card under the author's name."""
    return HtmlGenFile(url=src, filename=filename, size=size)
