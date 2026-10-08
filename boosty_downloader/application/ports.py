"""
Ports of the application layer: what the use cases need from the outside.

Implementations live in cli and infrastructure. They match structurally, without importing this module; conformance is checked where the app is put together. Shared argument and result types live in domain.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from boosty_downloader.domain.content_types import DownloadContentTypeFilter
    from boosty_downloader.domain.library import (
        LibraryAuthor,
        LibraryPost,
        LocatedPost,
        PostFilters,
        PostOverview,
    )
    from boosty_downloader.domain.library_marks import PostMarks
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


class PostCache(Protocol):
    """Which parts of a post an earlier run already saved."""

    def has_post(self, post_uuid: str) -> bool: ...

    def get_post_missing_parts(
        self,
        post_uuid: str,
        updated_at: datetime,
        required: list[DownloadContentTypeFilter],
    ) -> list[DownloadContentTypeFilter]: ...

    def cache_post(
        self,
        post_uuid: str,
        updated_at: datetime,
        was_downloaded: list[DownloadContentTypeFilter],
    ) -> None: ...

    def commit(self) -> None: ...


class FailureLog(Protocol):
    """Where failed downloads are recorded for the user to act on later."""

    async def add_error(self, error_id: str, message: str) -> None: ...


class CacheStorage(Protocol):
    """The cache of one creator as it sits on disk, without opening it."""

    def exists(self) -> bool: ...

    def remove(self) -> None: ...


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

        An existing post keeps its folder and marks. Failed folder-identity checks leave both posts unchanged.

        Raises:
            ValueError: The folder belongs to another post or would move this post.

        """
        ...

    def save_author(self, author: AuthorInfo) -> None:
        """Save one author's information, preserving all other authors."""
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


class LibraryReader(Protocol):
    """
    Library queries and user marks for one library root.

    Posts are identified by author and full post ID. Results and saved mark inputs are independent snapshots, including nested mutable values. Content updates belong to PostStore.
    """

    def authors(self) -> list[LibraryAuthor]:
        """List authors, including those whose posts have no saved blog information."""
        ...

    def list_posts(self, author: str, filters: PostFilters) -> list[PostOverview]:
        """Query one author's post overviews without loading full bodies."""
        ...

    def post(self, author: str, post_id: str) -> LibraryPost | None:
        """Return current access and any saved body, or None for an unknown post."""
        ...

    def get_marks(self, author: str, post_id: str) -> PostMarks | None:
        """Return saved or empty marks for a known post, or None for an unknown one."""
        ...

    def save_marks(self, author: str, post_id: str, marks: PostMarks) -> None:
        """
        Save the supplied marks without changing post content or computing timestamps.

        A saved post folder is required. Playback completion is decided by the caller.

        Raises:
            LookupError: The post has no saved folder.

        """
        ...
