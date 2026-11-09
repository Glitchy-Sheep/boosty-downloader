"""Run-scoped best-effort index updates after durable canonical writes."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

from sqlalchemy.exc import SQLAlchemyError

from boosty_downloader.infrastructure.library.index import IndexStatus
from boosty_downloader.infrastructure.library.index_projection import (
    project_author,
    project_post,
)
from boosty_downloader.infrastructure.library.index_sources import (
    locked_post_source,
    read_author_source,
    read_locked_fingerprint,
    read_post_source,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from boosty_downloader.infrastructure.library.index import LibraryIndex
    from boosty_downloader.infrastructure.library.index_sources import (
        AuthorSource,
        PostSource,
        SourceFingerprint,
    )
    from boosty_downloader.infrastructure.library.post_store import JsonPostStore

_Result = TypeVar('_Result')


class LibraryIndexWriter:
    """Disable optional indexing after its first failure in a download run."""

    def __init__(
        self,
        root: Path,
        *,
        index: LibraryIndex,
        store: JsonPostStore,
        warn: Callable[[str], None],
    ) -> None:
        self._root = root
        self._index = index
        self._store = store
        self._warn = warn
        self._prepared = False
        self._enabled = True

    def prepare(self) -> None:
        """Check or rebuild the index at most once for this run."""
        if self._prepared:
            return
        self._prepared = True
        status = self._attempt(self._index.ensure)
        if status is IndexStatus.corrupt:
            self._warn(
                f'Rebuilt damaged library index at {self._index.configured_path}.'
            )

    def capture_locked(self, author: str) -> SourceFingerprint | None:
        """Capture the canonical access version without changing any source."""
        return self._attempt(lambda: read_locked_fingerprint(self._root, author))

    def save_post(self, folder: str, author: str, post_id: str) -> None:
        """Update the exact saved folder without a library-wide scan."""
        self.prepare()
        self._attempt(lambda: self._save_post(folder, author, post_id))

    def save_author(self, author: str) -> None:
        """Refresh display metadata independently of access-row completeness."""
        self.prepare()
        self._attempt(
            lambda: self._index.upsert_author_metadata(
                project_author(read_author_source(self._root, author))
            )
        )

    def save_access(
        self,
        author: str,
        post_id: str,
        previous: SourceFingerprint | None,
    ) -> None:
        """Update one observed post with its whole access-file version."""
        self.prepare()
        self._attempt(lambda: self._save_access(author, post_id, previous))

    def _save_post(self, folder: str, author: str, post_id: str) -> None:
        source = read_author_source(self._root, author)
        post = read_post_source(
            self._root, folder, locked_post=source.locked_posts.get(post_id)
        )
        if post is None:
            message = f'Saved post disappeared before indexing: {folder}'
            raise FileNotFoundError(message)
        self._index.upsert_post(project_post(post))

    def _save_access(
        self,
        author: str,
        post_id: str,
        previous: SourceFingerprint | None,
    ) -> None:
        source = read_author_source(self._root, author)
        post = self._access_source(source, post_id)
        self._index.update_access(
            project_author(source),
            post_id,
            project_post(post) if post is not None else None,
            previous_locked_fingerprint=previous,
        )

    def _access_source(self, author: AuthorSource, post_id: str) -> PostSource | None:
        locked = author.locked_posts.get(post_id)
        located = self._store.find_post(author.author, post_id)
        if located is not None:
            post = read_post_source(self._root, located.folder, locked_post=locked)
            if post is not None:
                return post
        return locked_post_source(self._root, locked) if locked is not None else None

    def _attempt(self, operation: Callable[[], _Result]) -> _Result | None:
        if not self._enabled:
            return None
        try:
            return operation()
        except (OSError, ValueError, RuntimeError, SQLAlchemyError) as error:
            self._enabled = False
            self._warn(
                f'Library index update failed at {self._index.configured_path} '
                f'({type(error).__name__}). Downloads will continue without index '
                'updates. Check the cache directory or use --cache-dir with a '
                'writable local folder, then run reindex for this library.'
            )
            return None
