"""
Library lookup, query and detail values shared by storage callers.

Storage returns independent snapshots, including mutable records nested in frozen result envelopes. Folder paths are portable POSIX strings relative to the library root.
"""

from dataclasses import dataclass
from enum import Enum

from boosty_downloader.domain.stored_post import AuthorInfo, PostMetadata, StoredPost


@dataclass(frozen=True, slots=True)
class LocatedPost:
    """An existing post folder; a missing record allows recovery of retained files."""

    folder: str
    record: StoredPost | None = None


@dataclass(frozen=True, slots=True)
class LibraryAuthor:
    """A known author whose blog details may not have been fetched successfully."""

    author: str
    info: AuthorInfo | None = None


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


@dataclass(frozen=True, slots=True)
class PostFilters:
    """Filters for the posts of one author."""

    text: str = ''
    kind: LibraryContentKind | None = None
    unseen_only: bool = False
    tag: str | None = None


@dataclass(frozen=True, slots=True)
class PostOverview:
    """Current post metadata and access without body or media inventory."""

    post: PostMetadata
    access: PostAccess


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
