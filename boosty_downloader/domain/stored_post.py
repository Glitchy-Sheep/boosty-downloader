"""
Persistent post content and local media history.

StoredPost keeps the complete post body and each media piece's local state across download runs.

For example, a user downloads only text, then returns a week later to download videos. The record retains the text, video references and saved-file state so a later run can identify missing media and rebuild the complete page using files saved across both runs.

Datetimes are timezone-aware UTC values. Paths are portable relative strings.
Storage adapters validate and serialize these records.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Literal, TypeAlias

from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)


class MediaKind(str, Enum):
    """Kinds of pieces in a post's media inventory."""

    image = 'image'
    file = 'file'
    audio = 'audio'
    boosty_video = 'boosty_video'
    external_video = 'external_video'


class MediaStatus(str, Enum):
    """Local file state, independent of removal from the author's post."""

    pending = 'pending'
    downloaded = 'downloaded'
    failed = 'failed'
    unavailable = 'unavailable'
    deleted = 'deleted'


@dataclass
class LineBreak:
    """An explicit break within text, including text in a list item."""


@dataclass
class ParagraphBreak:
    """End the current paragraph; consecutive boundaries preserve blank paragraphs."""


@dataclass
class TextBlock:
    """An ordered run of styled text with inline line breaks."""

    fragments: list[PostDataChunkText.TextFragment | LineBreak]


TextContent: TypeAlias = TextBlock | ParagraphBreak


@dataclass
class ListItem:
    """Text and nested items in a stored list."""

    data: list[TextContent]
    nested_items: list['ListItem'] = field(default_factory=list['ListItem'])


@dataclass
class ListBlock:
    """An ordered or unordered list in the post body."""

    items: list[ListItem]
    style: PostDataChunkTextualList.ListStyle = (
        PostDataChunkTextualList.ListStyle.unordered
    )


@dataclass
class MediaBlock:
    """A reference to a piece in the owning post's media inventory."""

    media_id: str


Block: TypeAlias = TextContent | ListBlock | MediaBlock


@dataclass
class PostMetadata:
    """The overview shared by saved and locked posts."""

    id: str
    author: str
    url: str
    title: str
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list[str])
    tier: str | None = None
    # Monthly subscription and one-off purchase prices in RUB; None means unknown.
    tier_price_rub: float | None = None
    post_price_rub: float | None = None
    likes: int = 0
    comments: int = 0
    # Current remote counts by API kind, not local saved-file counts.
    content_counters: dict[str, int] = field(default_factory=dict[str, int])


@dataclass
class PostSync:
    """Record creation and synchronization times."""

    # First record creation, including a text-only or filtered run.
    first_downloaded_at: datetime
    synced_at: datetime
    # Last successful page render; None if no page has been built.
    page_template: int | None = None
    origin: Literal['api'] = 'api'


@dataclass
class MediaEntry:
    """A known piece and its local file history, keyed by identity in its post."""

    kind: MediaKind
    status: MediaStatus
    added_at: datetime
    # Retained inventory order, including removed pieces. Body order comes from blocks.
    position: int
    removed_at: datetime | None = None
    # Post-relative; a reserved path survives deletion and author removal.
    path: str | None = None
    # Last observed bytes on disk, including user edits. None means unknown.
    size: int | None = None
    title: str | None = None
    filename: str | None = None
    artist: str | None = None
    duration: timedelta | None = None
    width: int | None = None
    height: int | None = None
    # Post-relative, including when the full video is not downloaded.
    preview_path: str | None = None
    error: str | None = None


@dataclass
class StoredPost:
    """Complete current body and retained media history of a saved post."""

    post: PostMetadata
    sync: PostSync
    blocks: list[Block] = field(default_factory=list[Block])
    # Identity is local to this post: kind:Boosty-id or external_video:URL.
    media: dict[str, MediaEntry] = field(default_factory=dict[str, MediaEntry])


@dataclass
class LockedPost:
    """A currently inaccessible post's overview, with no post folder of its own."""

    post: PostMetadata
    synced_at: datetime
    # Relative to the author folder.
    teaser_path: str | None = None


@dataclass
class AuthorInfo:
    """Blog details; local library counts are computed separately."""

    author: str
    synced_at: datetime
    title: str | None = None
    owner_name: str | None = None
    # Full plain text with paragraph boundaries.
    description: str | None = None
    # Relative to the author folder.
    avatar_path: str | None = None
    cover_path: str | None = None
    remote_post_count: int | None = None
