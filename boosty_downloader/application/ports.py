"""
Ports of the application layer: what the use cases need from the outside.

Ports describe dependencies without selecting their implementations. Conformance is checked where the app is put together. Shared argument and result types live in domain.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, TypeAlias

if TYPE_CHECKING:
    from collections.abc import Iterator
    from uuid import UUID

    from boosty_downloader.domain.library import (
        LibraryAuthor,
        LibraryPostDetails,
        LocatedPost,
        PostFilters,
        PostList,
        SavedPage,
        SavedPost,
        TagCount,
    )
    from boosty_downloader.domain.library_marks import PostMarks
    from boosty_downloader.domain.library_media import (
        LibraryMediaItem,
        LibraryMediaPage,
        LibraryMediaView,
        MediaFilters,
        MediaIdentity,
    )
    from boosty_downloader.domain.library_mutations import (
        BulkMarkProgress,
        PostMarkResult,
    )
    from boosty_downloader.domain.stored_post import (
        AuthorInfo,
        LockedPost,
        PostMetadata,
        StoredPost,
    )


class ProgressReporter(Protocol):
    """Progress bars and messages of a run, as the use cases see them."""

    def create_task(
        self, name: str, total: int | None = None, indent_level: int = 0
    ) -> UUID: ...

    def update_task(
        self,
        task_uuid: UUID,
        advance: int = 1,
        total: int | None = None,
        description: str | None = None,
    ) -> None: ...

    def complete_task(self, task_uuid: UUID) -> None: ...

    def info(self, message: str) -> None: ...

    def success(self, message: str) -> None: ...

    def warn(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...

    def notice(self, message: str) -> None: ...


class FailureLog(Protocol):
    """Where failed downloads are recorded for the user to act on later."""

    async def add_error(self, error_id: str, message: str) -> None: ...


class PostStore(Protocol):
    """
    Persistent post records for one library root, keyed by author and full post ID.

    Folders are portable POSIX paths relative to the library root. Saved inputs and returned records are independent snapshots, including nested mutable values.
    """

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        """
        Find a post's existing folder and record without persistent writes.

        Return None when the folder is absent, or LocatedPost with no record when only the folder survives. Corrupt records raise an error.
        """
        ...

    def choose_post_folder(self, post: PostMetadata) -> str:
        """Choose a new post's folder without creating or reserving it."""
        ...

    def save_post(self, folder: str, record: StoredPost) -> None:
        """
        Atomically save the full record without changing current access.

        The folder must be valid for the record under the adapter's layout, normally obtained through lookup or choice. An existing post keeps its folder and marks. Failed folder-identity checks leave both posts unchanged.

        Raises:
            ValueError: The folder is invalid, belongs to another post or would move this post.

        """
        ...

    def load_author(self, author: str) -> AuthorInfo | None:
        """
        Load an independent author snapshot without persistent writes.

        Return None when no author record exists. Unreadable records raise an error.
        """
        ...

    def save_author(self, author: AuthorInfo) -> None:
        """Save one author's information, preserving all other authors."""
        ...

    def load_locked_post(self, author: str, post_id: str) -> LockedPost | None:
        """
        Read an independent access observation without changing the library.

        Return None for an unknown post.
        Invalid or unreadable records raise their error.
        """
        ...

    def save_locked_post(self, post: LockedPost) -> None:
        """
        Record current lack of access while retaining any saved content and marks.

        No post folder is created. A saved record, its folder and media remain unchanged.
        """
        ...

    def clear_locked_post(self, author: str, post_id: str) -> None:
        """
        Clear recorded lack of access after the live post confirms access.

        Preserve saved content and marks. An absent locked observation is a no-op.
        """
        ...


class StoredPostCollection(Protocol):
    """Enumerate and save canonical records independently of the browsing index."""

    def iter_saved_posts(self, author: str | None = None) -> Iterator[SavedPost]:
        """Read fresh independent records for one author or the entire library."""
        ...

    def save_post(self, folder: str, record: StoredPost) -> None:
        """Atomically save a record in its confirmed folder, preserving other files."""
        ...


MediaUrl: TypeAlias = Callable[[str], str]


class PostBodyRenderer(Protocol):
    """Render a saved body with URLs for its post-relative media paths."""

    def render(self, record: StoredPost, *, media_url: MediaUrl) -> str:
        """Return the shared post body without changing records or writing a page."""
        ...


class LibraryReader(Protocol):
    """
    Library queries and user marks for one library root.

    Posts are identified by author and full post ID. Results and saved mark inputs are independent snapshots, including nested mutable values. Content updates belong to PostStore.

    Read methods raise domain LibraryReadError when storage cannot provide valid data. Missing resources return None or empty collections; corrupt records remain errors.

    Mutation methods raise LibraryWriteError on failed persistence or projection, and LibraryMarkConflictError when the saved state forbids a change. A durable canonical mark can survive a failed projection; repeating the request repairs it.
    """

    def authors(self) -> list[LibraryAuthor]:
        """List authors, including those whose posts have no saved blog information."""
        ...

    def author(self, author: str) -> LibraryAuthor | None:
        """Read one author's details and totals, or None for an unknown author."""
        ...

    def has_author(self, author: str) -> bool:
        """Check whether the author belongs to this library without loading totals."""
        ...

    def tags(self, author: str) -> list[TagCount]:
        """List exact tags and distinct post counts for one author."""
        ...

    def list_posts(self, author: str, filters: PostFilters) -> PostList:
        """Query indexed rows and totals without loading full bodies."""
        ...

    def list_media(
        self, author: str, view: LibraryMediaView, filters: MediaFilters
    ) -> LibraryMediaPage:
        """Query downloaded pieces, shared posts and filtered totals from one snapshot."""
        ...

    def post(self, author: str, post_id: str) -> LibraryPostDetails | None:
        """Read fresh content, access, marks and cover, or None for an unknown post."""
        ...

    def media_path(self, author: str, identity: MediaIdentity) -> str | None:
        """Return a downloaded piece's recorded library-relative path, or None."""
        ...

    def post_folder(self, author: str, post_id: str) -> str | None:
        """Return a post's recorded library-relative folder, or None if unsaved."""
        ...

    def saved_page(self, author: str, author_relative_path: str) -> SavedPage | None:
        """Confirm a generated page's stored ownership without granting file access."""
        ...

    def get_marks(self, author: str, post_id: str) -> PostMarks | None:
        """Return saved or empty marks for a known post, or None for an unknown one."""
        ...

    def save_marks(self, author: str, post_id: str, marks: PostMarks) -> None:
        """
        Save the supplied marks without changing post content or computing timestamps.

        A saved folder with confirmed full post identity is required. Playback completion is decided by the caller.

        Raises:
            LookupError: The post has no confirmed saved folder.

        """
        ...

    def set_seen(
        self, author: str, post_id: str, *, seen: bool
    ) -> PostMarkResult | None:
        """Acknowledge or clear seen content; unknown posts return None."""
        ...

    def set_favorite(
        self, author: str, post_id: str, *, favorite: bool
    ) -> PostMarkResult | None:
        """Change only favorite state; unknown posts return None."""
        ...

    def set_seen_many(
        self,
        author: str,
        filters: PostFilters,
        *,
        seen: bool,
        progress: Callable[[BulkMarkProgress], None] | None = None,
    ) -> int | None:
        """Mark a fixed selection, reporting changes; unknown authors return None."""
        ...

    def set_position(
        self,
        author: str,
        identity: MediaIdentity,
        seconds: float,
        duration: float,
    ) -> LibraryMediaItem | None:
        """Update retained playable media; unknown posts or pieces return None."""
        ...
