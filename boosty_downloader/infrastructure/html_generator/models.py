"""HTML generator models that are independent from domain types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from datetime import timedelta


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


@dataclass(frozen=True, slots=True)
class HtmlLineBreak:
    """A line break within a paragraph or heading."""


HtmlInline: TypeAlias = HtmlTextFragment | HtmlLineBreak


@dataclass(frozen=True, slots=True)
class HtmlGenParagraph:
    """A paragraph, including an explicitly empty one."""

    fragments: list[HtmlInline]


@dataclass(frozen=True, slots=True)
class HtmlGenHeading:
    """A heading whose level applies to every inline fragment."""

    level: int
    fragments: list[HtmlInline]


HtmlTextBlock: TypeAlias = HtmlGenParagraph | HtmlGenHeading


@dataclass
class HtmlGenImage:
    """Image content for HTML generation."""

    url: str
    alt: str = 'Image'


@dataclass
class HtmlGenVideo:
    """Video content for HTML generation."""

    url: str
    title: str | None = None


class HtmlListStyle(Enum):
    """List style for HTML generation."""

    ORDERED = 'ordered'
    UNORDERED = 'unordered'


@dataclass
class HtmlListItem:
    """A single item in an HTML list."""

    data: list[HtmlGenText | HtmlTextBlock]
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
    # Bytes as the API reports them; None when unknown.
    size: int | None = None


@dataclass
class HtmlGenAudio:
    """Audio content for HTML generation."""

    url: str
    title: str | None = None


HtmlGenMedia: TypeAlias = HtmlGenImage | HtmlGenVideo | HtmlGenAudio | HtmlGenFile


@dataclass(frozen=True, slots=True)
class HtmlGenRemovedMedia:
    """Saved media removed from the post, in display order."""

    media: list[HtmlGenMedia]


class UnavailableKind(Enum):
    """What kind of media piece is missing from the page."""

    IMAGE = 'image'
    VIDEO = 'video'
    AUDIO = 'audio'
    FILE = 'file'


@dataclass
class HtmlGenUnavailable:
    """A media piece that did not download: the page marks its place and says why."""

    kind: UnavailableKind
    reason: str
    # The name the author gave the piece; empty for images, which have none.
    label: str = ''
    # Where the piece lives outside Boosty (external videos): the reader can try it there.
    source_url: str | None = None
    duration: timedelta | None = None


@dataclass(frozen=True, slots=True)
class HtmlGenNotDownloaded:
    """A media piece that has not been downloaded, with a link to its post."""

    kind: UnavailableKind
    post_url: str
    label: str = ''
    duration: timedelta | None = None


@dataclass(frozen=True, slots=True)
class HtmlGenDeleted:
    """A media piece whose saved file is missing from disk."""

    kind: UnavailableKind
    label: str = ''


# Union type for all HTML chunk types
HtmlGenChunk: TypeAlias = (
    HtmlGenText
    | HtmlTextBlock
    | HtmlGenList
    | HtmlGenMedia
    | HtmlGenRemovedMedia
    | HtmlGenUnavailable
    | HtmlGenNotDownloaded
    | HtmlGenDeleted
)
