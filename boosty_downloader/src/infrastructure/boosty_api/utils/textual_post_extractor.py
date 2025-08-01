"""Module to extract textual content from a post by its chunks"""

from __future__ import annotations

import json
from io import StringIO


def extract_textual_content(
    content: str,
) -> str:
    """Extract textual content from a post chunk Link/Text"""
    buffer = StringIO()

    # Merge all the text and link fragments into one file
    try:
        json_data: list[str] = json.loads(content)
    except json.JSONDecodeError:
        return buffer.getvalue()

    if len(json_data) == 0:
        return buffer.getvalue()

    clean_text = str(json_data[0])

    buffer.write(clean_text)

    return buffer.getvalue()
