"""Module to extract textual content from a post by its chunks"""

from __future__ import annotations

import json
from io import StringIO
from typing import TYPE_CHECKING

from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_link import (
    PostDataLink,
)

if TYPE_CHECKING:
    from boosty_downloader.src.boosty_api.models.post.post_data_types.post_data_text import (
        PostDataText,
    )


async def download_textual_content(
    textual_content: list[PostDataText | PostDataLink],
) -> StringIO:
    """Extract textual content from a post by its chunks"""
    post_text = StringIO()

    # Merge all the text and link fragments into one file
    for text_chunk in textual_content:
        try:
            json_data: list[str] = json.loads(text_chunk.content)
        except json.JSONDecodeError:
            continue

        if len(json_data) == 0:
            continue

        clean_text = str(json_data[0])

        if isinstance(text_chunk, PostDataLink):
            clean_text += f' [{text_chunk.url}]'

        post_text.write(clean_text + '\n')

    return post_text
