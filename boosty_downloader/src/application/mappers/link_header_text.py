"""
Mapper for converting textual Boosty API post data chunks to domain text object.

If the API responses change, this mapper may need to be updated accordingly.
"""

import json

from boosty_downloader.src.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataHeaderDTO,
    BoostyPostDataLinkDTO,
    BoostyPostDataTextDTO,
)


def _parse_header(style_definition: str) -> int:
    r"""
    Parse header level (h1/h2/h3...) from the style definition.

    Style definition usually comes as a 2nd field in the "content" field of PostDataText.

    ```
    "content": "[\"Hello, world!\", \"unstyled\", <---- [[0, 0, 13]]"
    ```
    """
    # These values were reverse engineered from Boosty API responses.
    header_possible_values = {
        'unstyled': 0,
        'header-one': 1,
        'header-two': 2,
        'header-three': 3,
        'header-four': 4,
        'header-five': 5,
        'header-six': 6,
    }

    # by default (and in other cases) have no header
    return header_possible_values.get(style_definition, 0)


def _create_style_bitmap(
    text_length: int, style_array: list[list[int]]
) -> list[set[int]]:
    """Create bitmap of styles for each character position."""
    bitmap: list[set[int]] = [set() for _ in range(text_length)]

    for style_desc in style_array:
        style_id, start_idx, end_idx = style_desc
        for i in range(start_idx, min(end_idx, text_length)):
            bitmap[i].add(style_id)

    return bitmap


def _create_text_fragments(
    text: str, style_bitmap: list[set[int]], header_level: int
) -> list[PostDataChunkText.TextFragment]:
    """Create text fragments based on style bitmap."""
    if not text:
        return []

    fragments: list[PostDataChunkText.TextFragment] = []
    current_fragment_start = 0
    current_styles: set[int] = style_bitmap[0] if style_bitmap else set()

    for i in range(1, len(text)):
        if i >= len(style_bitmap) or style_bitmap[i] != current_styles:
            fragment_text = text[current_fragment_start:i]
            fragment = PostDataChunkText.TextFragment(fragment_text)
            fragment.header_level = header_level
            fragment.style = _convert_style_set_to_text_style(current_styles)
            fragments.append(fragment)

            current_fragment_start = i
            current_styles = style_bitmap[i] if i < len(style_bitmap) else set()

    # Add the last fragment
    fragment_text = text[current_fragment_start:]
    fragment = PostDataChunkText.TextFragment(fragment_text)
    fragment.header_level = header_level
    fragment.style = _convert_style_set_to_text_style(current_styles)
    fragments.append(fragment)

    return fragments


def _convert_style_set_to_text_style(
    style_set: set[int],
) -> PostDataChunkText.TextFragment.TextStyle:
    """Convert set of style IDs to TextStyle object."""
    bold = 0
    italic = 2
    underline = 4

    text_style = PostDataChunkText.TextFragment.TextStyle()
    text_style.bold = bold in style_set
    text_style.italic = italic in style_set
    text_style.underline = underline in style_set

    return text_style


def _parse_content_field(
    content: str, modificator: str = ''
) -> list[PostDataChunkText.TextFragment]:
    def _extract_content_field(content: str) -> tuple[str, str, list[list[int]]]:
        r"""
        Extract text, style info, and style array from the content field.

        Boosty API returns "content" as a JSON-encoded string like this:
        "[\"Hello, world!\", \"unstyled\", [[0, 0, 13]]"

        The first part is just a text string, the other two parts are style information:
        - you can read about them in the _parse_style_array and _parse_header functions above.
        """
        try:
            parsed = json.loads(content)
            text = parsed[0]
            style_info = parsed[1]
            style_array = parsed[2]
        except json.JSONDecodeError:
            return content, '', []
        else:
            return text, style_info, style_array

    text, style_info, styles_array = _extract_content_field(content)

    if modificator == 'BLOCK_END':
        text += '\n'

    header_level = _parse_header(style_info)
    style_bitmap = _create_style_bitmap(len(text), styles_array)
    return _create_text_fragments(text, style_bitmap, header_level)


def to_domain_text_chunk(
    api_textual_dto: BoostyPostDataTextDTO
    | BoostyPostDataHeaderDTO
    | BoostyPostDataLinkDTO,
) -> list[PostDataChunkText.TextFragment]:
    """
    Convert API textual data chunks to domain text fragments.

    It uses the PostDataText, PostDataHeader, or PostDataLink DTOs
    to extract the content and convert it to a list of domain text fragments.
    """
    modificator = getattr(api_textual_dto, 'modificator', '')
    text_fragments = _parse_content_field(api_textual_dto.content, modificator)

    # Attach link information to the text fragments if any is present
    if isinstance(api_textual_dto, BoostyPostDataLinkDTO):
        for fragment in text_fragments:
            fragment.link_url = api_textual_dto.url

    return text_fragments
