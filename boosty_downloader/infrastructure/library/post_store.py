"""JSON-backed post records and access observations for one library run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.library import author_records
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.domain.library import LocatedPost
    from boosty_downloader.domain.stored_post import (
        AuthorInfo,
        LockedPost,
        PostMetadata,
        StoredPost,
    )


class JsonPostStore:
    """Persist post bodies, author details and separate access observations."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._posts = JsonPostRecords(self._root)

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        """Find a stable post folder and an independent saved record."""
        return self._posts.find_post(author, post_id)

    def choose_post_folder(self, post: PostMetadata) -> str:
        """Choose a free post folder without creating or reserving it."""
        return self._posts.choose_post_folder(post)

    def save_post(self, folder: str, record: StoredPost) -> None:
        """Save the complete body without clearing a locked observation."""
        self._posts.save_post(folder, record)

    def save_author(self, author: AuthorInfo) -> None:
        """Save one author's complete information snapshot."""
        author_records.write_author_record(self._root, author)

    def save_locked_post(self, post: LockedPost) -> None:
        """Record lack of access while keeping saved content and viewing marks."""
        author_records.save_locked_post(self._root, post)

    def clear_locked_post(self, author: str, post_id: str) -> None:
        """Clear only the named observation after live access is confirmed."""
        author_records.clear_locked_post(self._root, author, post_id)
