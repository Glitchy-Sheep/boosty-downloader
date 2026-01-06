"""
Module contains domain models for post data chunks.

These are used to represent different parts of a post, such as text, images, etc.
"""

from dataclasses import dataclass, field
from enum import Enum


@dataclass
class PostDataChunkAudio:
    """Represent an audio data chunk within a post."""

    url: str
    title: str


@dataclass
class PostDataChunkImage:
    """Represent an image data chunk within a post."""

    url: str


@dataclass
class PostDataChunkText:
    """
    Represent a textual data chunk within a post.

    It can contain multiple text fragments, each with optional styling and links.

    For example:
        - PostDataChunkText(
            text_fragments=[
                PostDataChunkText.TextFragment(text="Hello, world!", bold=True),
                PostDataChunkText.TextFragment(text="Visit Boosty", link_data="https://boosty.com", header_level=1),
                PostDataChunkText.TextFragment(text="This is a normal text."),
                PostDataChunkText.TextFragment(text="<NEW_LINE_SYMBOL>"),
            ]
    """

    @dataclass
    class TextFragment:
        """
        Represent a text fragment within a post with possibly additional styling.

        It also can contain a link to external resources (if link_data == None - it's just a text).
        """

        @dataclass
        class TextStyle:
            """Represent text styling options."""

            bold: bool = False
            italic: bool = False
            underline: bool = False

        text: str
        link_url: str | None = None
        header_level: int = 0  # Header level (0-6), 0 means no header
        style: TextStyle = field(default_factory=TextStyle)

    text_fragments: list[TextFragment]


@dataclass
class PostDataChunkBoostyVideo:
    """Represent a Boosty video data chunk within a post."""

    title: str
    url: str
    quality: str


@dataclass
class PostDataChunkExternalVideo:
    """
    Represent an external video data chunk within a post.

    Can be from: YouTube, Vimeo, etc.
    """

    url: str


@dataclass
class PostDataChunkFile:
    """Represent a file data chunk within a post."""

    url: str
    filename: str


@dataclass
class PostDataChunkTextualList:
    """
    Represent a list of text items within a post.

    Each item can be a simple text or a more complex structure with optional styling.
    """

    """ 📃 About this creepy structure:

    Lists can be nested, so we use a union type for items
    each level of nesting means a new list of items:

    ----------------------------------------------------------------------------
    # For example this:
    ----------------------------------------------------------------------------

    PostDataChunkTextualList(
        items=[
            PostDataChunkTextualList.ListItem(
                data=[PostDataChunkText(text="Item 1")],
                nested_items=[]
            ),
            PostDataChunkTextualList.ListItem(
                data=[PostDataChunkText(text="Nested list:")],
                nested_items=[
                    PostDataChunkTextualList.ListItem(
                        data=[PostDataChunkText(text="Item 2")],
                        nested_items=[]
                    ),
                    PostDataChunkTextualList.ListItem(
                        data=[PostDataChunkText(text="Item 3")],
                        nested_items=[]
                    )
                ]
            )
        ]
    )

    ----------------------------------------------------------------------------
    # Becomes this:
    ----------------------------------------------------------------------------

    - Item 1
    - Nested list:
      - Item 2
      - Item 3
    """

    @dataclass
    class ListItem:
        """'Represent a single item in a textual list."""

        data: list['PostDataChunkText']
        nested_items: list['PostDataChunkTextualList.ListItem']

    class ListStyle(Enum):
        """Style of the list, can be ordered or unordered."""

        ordered = 'ordered'
        unordered = 'unordered'

    items: list[ListItem]
