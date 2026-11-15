"""Durable JSON storage with optional run-scoped search-index updates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.library.index_writer import LibraryIndexWriter
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from collections.abc import Callable, Collection
    from pathlib import Path

    from boosty_downloader.domain.library import LocatedPost
    from boosty_downloader.domain.stored_post import (
        AuthorInfo,
        LockedPost,
        PostMetadata,
        StoredPost,
    )
    from boosty_downloader.infrastructure.library.index import LibraryIndex


class IndexedJsonPostStore:
    """Canonical writes succeed independently of the disposable index."""

    def __init__(
        self, root: Path, *, index: LibraryIndex, warn: Callable[[str], None]
    ) -> None:
        root = root.resolve()
        self._store = JsonPostStore(root)
        self._writer = LibraryIndexWriter(
            root, index=index, store=self._store, warn=warn
        )

    def prepare(self) -> None:
        """Prepare optional indexing once after the library has been initialized."""
        self._writer.prepare()

    def find_post(self, author: str, post_id: str) -> LocatedPost | None:
        return self._store.find_post(author, post_id)

    def choose_post_folder(
        self, post: PostMetadata, *, reserved_folders: Collection[str] = ()
    ) -> str:
        return self._store.choose_post_folder(post, reserved_folders=reserved_folders)

    def save_post(self, folder: str, record: StoredPost) -> None:
        self._store.save_post(folder, record)
        self._writer.save_post(folder, record.post.author, record.post.id)

    def load_author(self, author: str) -> AuthorInfo | None:
        return self._store.load_author(author)

    def save_author(self, author: AuthorInfo) -> None:
        self._store.save_author(author)
        self._writer.save_author(author.author)

    def load_locked_post(self, author: str, post_id: str) -> LockedPost | None:
        return self._store.load_locked_post(author, post_id)

    def save_locked_post(self, post: LockedPost) -> None:
        previous = self._writer.capture_locked(post.post.author)
        self._store.save_locked_post(post)
        self._writer.save_access(post.post.author, post.post.id, previous)

    def clear_locked_post(self, author: str, post_id: str) -> None:
        previous = self._writer.capture_locked(author)
        self._store.clear_locked_post(author, post_id)
        self._writer.save_access(author, post_id, previous)
