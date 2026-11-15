"""Primary database facade for the downloader's complete PostStore contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.library.db_author_records import (
    DatabaseAuthorRecords,
)
from boosty_downloader.infrastructure.library.db_post_records import DatabasePostRecords

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from boosty_downloader.domain.library import LocatedPost
    from boosty_downloader.domain.stored_post import (
        AuthorInfo,
        LockedPost,
        PostMetadata,
        StoredPost,
    )
    from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


class DatabasePostStore:
    """Compose saved posts and access observations while borrowing database ownership."""

    def __init__(self, root: Path, database: LibraryDatabase) -> None:
        self._posts = DatabasePostRecords(root, database)
        self._authors = DatabaseAuthorRecords(root, database)

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        """Find the saved generation or a recoverable unowned folder without writes."""
        return self._posts.find_post(author, post_id)

    def choose_post_folder(
        self, post: PostMetadata, *, reserved_folders: Collection[str] = ()
    ) -> str:
        """Choose a portable post path without creating or reserving it."""
        return self._posts.choose_post_folder(post, reserved_folders=reserved_folders)

    def save_post(self, folder: str, record: StoredPost) -> None:
        """Save one generation without clearing an independent access observation."""
        self._posts.save_post(folder, record)

    def load_author(self, author: str) -> AuthorInfo | None:
        """Read a detached author snapshot without creating its directory."""
        return self._authors.load_author(author)

    def save_author(self, author: AuthorInfo) -> None:
        """Replace the author's complete metadata snapshot."""
        self._authors.save_author(author)

    def load_locked_post(self, author: str, post_id: str) -> LockedPost | None:
        """Read a detached observation independently of saved content."""
        return self._authors.load_locked_post(author, post_id)

    def save_locked_post(self, post: LockedPost) -> None:
        """Record current lack of access while preserving saved content and marks."""
        self._authors.save_locked_post(post)

    def clear_locked_post(self, author: str, post_id: str) -> None:
        """Clear only an explicitly restored post's access observation."""
        self._authors.clear_locked_post(author, post_id)
