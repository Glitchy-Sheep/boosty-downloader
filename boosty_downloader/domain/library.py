"""
Library lookup, query and detail values shared by storage callers.

Storage returns independent snapshots, including mutable records nested in frozen result envelopes. Folder paths are portable POSIX strings relative to the library root.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.domain.stored_post import AuthorInfo, PostMetadata, StoredPost


@dataclass(frozen=True, slots=True)
class PostIdentity:
    """A full post key, independent of folder names and index row numbers."""

    author: str
    post_id: str


@dataclass(frozen=True, slots=True)
class LocatedPost:
    """An existing post folder; a missing record allows recovery of retained files."""

    folder: str
    record: StoredPost | None = None


@dataclass(frozen=True, slots=True)
class SavedPost:
    """A complete canonical record in its confirmed library-relative folder."""

    folder: str
    record: StoredPost


@dataclass(frozen=True, slots=True)
class SavedPage:
    """A rendered page's recorded ownership, with library-relative folder and path."""

    folder: str
    path: str


@dataclass(frozen=True, slots=True)
class MediaCounts:
    """Media counts for a selection, with both video sources combined."""

    images: int = 0
    videos: int = 0
    files: int = 0
    audio: int = 0


@dataclass(frozen=True, slots=True)
class MediaStorage:
    """Recorded bytes of downloaded media, including retained removed copies."""

    images: int = 0
    videos: int = 0
    files: int = 0
    audio: int = 0


@dataclass(frozen=True, slots=True)
class AuthorCounts:
    """Known posts and their current access and viewing totals."""

    posts: int = 0
    locked: int = 0
    unseen: int = 0
    favorites: int = 0


@dataclass(frozen=True, slots=True)
class LibraryAuthor:
    """A known author whose blog details may not have been fetched successfully."""

    author: str
    info: AuthorInfo | None = None
    counts: AuthorCounts = AuthorCounts()
    storage: MediaStorage = MediaStorage()


class PostAccess(str, Enum):
    """Current observed access, independent of a retained saved body."""

    open = 'open'
    locked = 'locked'


class LibraryContentKind(str, Enum):
    """Viewer categories; video includes platform and external videos."""

    video = 'video'
    image = 'image'
    file = 'file'
    audio = 'audio'


class PostOrder(str, Enum):
    """Post date order, with full post identity breaking date ties."""

    newest = 'newest'
    oldest = 'oldest'


@dataclass(frozen=True, slots=True)
class PostFilters:
    """Filters for the posts of one author."""

    text: str = ''
    kind: LibraryContentKind | None = None
    unseen_only: bool = False
    tag: str | None = None
    favorites_only: bool = False
    locked_only: bool = False
    incomplete_only: bool = False
    order: PostOrder = PostOrder.newest


@dataclass(frozen=True, slots=True)
class PostOverview:
    """Current post metadata and access without body or media inventory."""

    post: PostMetadata
    access: PostAccess


@dataclass(frozen=True, slots=True)
class SearchRun:
    """Plain text and whether it matched; never rendered HTML."""

    text: str
    matched: bool


@dataclass(frozen=True, slots=True)
class SearchMatch:
    """Original title and optional body context with search hits marked."""

    title: tuple[SearchRun, ...]
    text: tuple[SearchRun, ...] | None


@dataclass(frozen=True, slots=True)
class PostRow:
    """An indexed browsing snapshot without loading the full saved body."""

    overview: PostOverview
    cover_path: str | None
    counts: MediaCounts
    missing_media: int
    seen_at: datetime | None
    favorite: bool
    pieces_added_at: datetime | None
    match: SearchMatch | None = None


@dataclass(frozen=True, slots=True)
class MonthCount:
    """Number of filtered posts in a UTC calendar month, formatted YYYY-MM."""

    month: str
    count: int


@dataclass(frozen=True, slots=True)
class PostList:
    """Filtered rows with month counts and the total for that same selection."""

    rows: list[PostRow]
    months: list[MonthCount]
    total: int


@dataclass(frozen=True, slots=True)
class TagCount:
    """Distinct posts carrying one exact tag of an author."""

    tag: str
    count: int


@dataclass(frozen=True, slots=True)
class LibraryPost:
    """
    Current overview with an independently retained saved body.

    A saved body has both record and folder; a locked-only post has neither. The overview may contain newer locked metadata than the saved record. The teaser path is relative to the author folder.
    """

    overview: PostOverview
    record: StoredPost | None = None
    folder: str | None = None
    teaser_path: str | None = None


@dataclass(frozen=True, slots=True)
class LibraryPostDetails:
    """Fresh content and marks from one source read; cover is library-relative."""

    content: LibraryPost
    marks: PostMarks
    cover_path: str | None
