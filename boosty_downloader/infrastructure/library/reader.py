"""Indexed library queries with fresh canonical post details and viewing marks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.domain.library import LibraryPost, PostAccess, PostOverview
from boosty_downloader.infrastructure.library._reader_queries import (
    read_authors,
    read_overviews,
    read_post_location,
)
from boosty_downloader.infrastructure.library.author_records import read_locked_posts
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.index_projection import project_post
from boosty_downloader.infrastructure.library.index_sources import read_post_source
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.domain.library import LibraryAuthor, PostFilters
    from boosty_downloader.domain.library_marks import PostMarks
    from boosty_downloader.infrastructure.library.index import IndexSyncCounts
    from boosty_downloader.infrastructure.library.index_sources import PostSource


class JsonLibraryReader:
    """Read independent snapshots; call prepare explicitly before using the index."""

    def __init__(self, root: Path, *, index_path: Path | None = None) -> None:
        self._root = root
        self._index = LibraryIndex(root, index_path=index_path)

    def prepare(self) -> IndexSyncCounts:
        """Synchronize the disposable projection without modifying canonical records."""
        return self._index.synchronize()

    def authors(self) -> list[LibraryAuthor]:
        """List known authors from the index, including authors without details."""
        with self._index.connect() as connection:
            return read_authors(connection)

    def list_posts(self, author: str, filters: PostFilters) -> list[PostOverview]:
        """Return filtered metadata snapshots without opening post JSON files."""
        with self._index.connect() as connection:
            return read_overviews(connection, author, filters)

    def post(self, author: str, post_id: str) -> LibraryPost | None:
        """Open the known folder and validate its full identity against current access."""
        with self._index.connect() as connection:
            indexed = read_post_location(connection, author, post_id)
        if indexed is None:
            return None
        locked = read_locked_posts(self._root, author).get(post_id)
        if indexed.folder is not None:
            source = read_post_source(self._root, indexed.folder, locked_post=locked)
            if source is not None:
                _check_identity(source, author, post_id)
                return source.post
        if locked is not None:
            return LibraryPost(
                PostOverview(locked.post, PostAccess.locked),
                teaser_path=locked.teaser_path,
            )
        return None

    def get_marks(self, author: str, post_id: str) -> PostMarks | None:
        """Read validated canonical marks, independent of cached indexed values."""
        root = self._canonical_root()
        return JsonPostMarks(root).get_marks(author, post_id)

    def save_marks(self, author: str, post_id: str, marks: PostMarks) -> None:
        """Persist marks first; a failed projection update leaves canonical marks saved."""
        root = self._canonical_root()
        JsonPostMarks(root).save_marks(author, post_id, marks)
        source = _saved_source(root, author, post_id)
        self._index.upsert_post(project_post(source))

    def _canonical_root(self) -> Path:
        with self._index.connect():
            return self._root.resolve()


def _saved_source(root: Path, author: str, post_id: str) -> PostSource:
    located = JsonPostRecords(root).find_post(author, post_id)
    if located is not None and located.record is not None:
        locked = read_locked_posts(root, author).get(post_id)
        source = read_post_source(root, located.folder, locked_post=locked)
        if source is not None:
            _check_identity(source, author, post_id)
            return source
    message = f'The saved post disappeared while updating marks: {author}/{post_id}'
    raise LookupError(message)


def _check_identity(source: PostSource, author: str, post_id: str) -> None:
    record = source.post.record
    if record is None or record.post.author != author or record.post.id != post_id:
        message = f'The saved folder no longer belongs to {author}/{post_id}'
        raise InvalidPostRecordError(message)
