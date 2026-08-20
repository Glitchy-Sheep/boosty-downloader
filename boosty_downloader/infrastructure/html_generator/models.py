"""HTML generator models that are independent from domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass
class HtmlTextStyle:
    """Text styling options for HTML generation."""

    bold: bool = False
    italic: bool = False
    underline: bool = False


@dataclass
class HtmlTextFragment:
    """A text fragment with optional styling and links."""

    text: str
    link_url: str | None = None
    header_level: int = 0  # 0 means no header, 1-6 for h1-h6
    style: HtmlTextStyle = field(default_factory=HtmlTextStyle)


@dataclass
class HtmlGenText:
    """Text content for HTML generation."""

    text_fragments: list[HtmlTextFragment]


@dataclass
class HtmlGenImage:
    """Image content for HTML generation."""

    url: str
    alt: str = 'Image'
    width: int | None = None
    height: int | None = None


@dataclass
class HtmlGenVideo:
    """Video content for HTML generation."""

    url: str
    title: str | None = None
    poster: str | None = None


class HtmlListStyle(Enum):
    """List style for HTML generation."""

    ORDERED = 'ordered'
    UNORDERED = 'unordered'


@dataclass
class HtmlListItem:
    """A single item in an HTML list."""

    data: list[HtmlGenText]
    nested_items: list[HtmlListItem] = field(default_factory=list['HtmlListItem'])


@dataclass
class HtmlGenList:
    """List content for HTML generation."""

    items: list[HtmlListItem]
    style: HtmlListStyle = HtmlListStyle.UNORDERED


@dataclass
class HtmlGenFile:
    """File content for HTML generation."""

    url: str
    filename: str
    title: str | None = None


@dataclass
class HtmlGenAudio:
    """Audio content for HTML generation."""

    url: str
    title: str | None = None


# Union type for all HTML chunk types
HtmlGenChunk = (
    HtmlGenText | HtmlGenImage | HtmlGenVideo | HtmlGenList | HtmlGenFile | HtmlGenAudio
)
