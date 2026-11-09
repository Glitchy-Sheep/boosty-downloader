"""Indexed library queries with fresh canonical post details and viewing marks."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import PurePosixPath
from sqlite3 import Error as SQLiteError
from threading import Lock
from typing import TYPE_CHECKING, Final

from sqlalchemy.exc import SQLAlchemyError

from boosty_downloader.domain.library import LibraryPostDetails, SavedPage
from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.infrastructure.library._reader_authors import (
    has_author,
    read_author,
    read_authors,
    read_tags,
)
from boosty_downloader.infrastructure.library._reader_media import read_media
from boosty_downloader.infrastructure.library._reader_mutations import (
    JsonMarkMutations,
    current_time,
    writing_marks,
)
from boosty_downloader.infrastructure.library._reader_queries import (
    read_post_id_by_folder,
    read_post_location,
    read_posts,
)
from boosty_downloader.infrastructure.library.author_records import read_locked_posts
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError
from boosty_downloader.infrastructure.library.index import (
    IndexNotPreparedError,
    LibraryIndex,
)
from boosty_downloader.infrastructure.library.index_projection import project_post
from boosty_downloader.infrastructure.library.index_sources import (
    locked_post_source,
    read_post_source,
)
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from datetime import datetime
    from pathlib import Path

    from boosty_downloader.domain.library import (
        LibraryAuthor,
        PostFilters,
        PostList,
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
    from boosty_downloader.domain.stored_post import StoredPost
    from boosty_downloader.infrastructure.library.index import IndexSyncCounts
    from boosty_downloader.infrastructure.library.index_sources import PostSource

_SAVED_PAGE_NAME: Final = 'post.html'
_AUTHOR_PAGE_DEPTH: Final = 2


class JsonLibraryReader:
    """Read independent snapshots; call prepare explicitly before using the index."""

    def __init__(
        self,
        root: Path,
        *,
        index_path: Path | None = None,
        clock: Callable[[], datetime] = current_time,
    ) -> None:
        self._root = root
        self._index = LibraryIndex(root, index_path=index_path)
        self._mutation_lock = Lock()
        self._mutations = JsonMarkMutations(root, self._index, clock)

    def prepare(self) -> IndexSyncCounts:
        """Synchronize the disposable projection without modifying canonical records."""
        with self._mutation_lock:
            return self._index.synchronize()

    def authors(self) -> list[LibraryAuthor]:
        """List known authors from the index, including authors without details."""
        with _reading_library(), self._index.connect() as connection:
            return read_authors(connection)

    def author(self, author: str) -> LibraryAuthor | None:
        """Return one author's metadata, post counts and recorded media bytes."""
        with _reading_library(), self._index.connect() as connection:
            return read_author(connection, author)

    def has_author(self, author: str) -> bool:
        """Check the indexed author identity without querying its posts or media."""
        with _reading_library(), self._index.connect() as connection:
            return has_author(connection, author)

    def tags(self, author: str) -> list[TagCount]:
        """Count distinct indexed posts for every exact tag of one author."""
        with _reading_library(), self._index.connect() as connection:
            return read_tags(connection, author)

    def list_posts(self, author: str, filters: PostFilters) -> PostList:
        """Return filtered browsing snapshots without opening canonical JSON files."""
        with _reading_library(), self._index.connect() as connection:
            return read_posts(connection, author, filters)

    def list_media(
        self, author: str, view: LibraryMediaView, filters: MediaFilters
    ) -> LibraryMediaPage:
        """Read recorded media and totals without inspecting canonical files."""
        with _reading_library(), self._index.connect() as connection:
            return read_media(connection, author, view, filters)

    def post(self, author: str, post_id: str) -> LibraryPostDetails | None:
        """Open the known folder and validate its full identity against current access."""
        with _reading_library():
            with self._index.connect() as connection:
                indexed = read_post_location(connection, author, post_id)
            if indexed is None:
                return None
            return _read_details(self._root, author, post_id, indexed.folder)

    def saved_page(self, author: str, author_relative_path: str) -> SavedPage | None:
        """Prove rendered-page ownership from one indexed folder and fresh record."""
        folder = _page_folder(author, author_relative_path)
        if folder is None:
            return None
        with _reading_library():
            with self._index.connect() as connection:
                post_id = read_post_id_by_folder(connection, author, folder)
            if post_id is None:
                return None
            return _read_saved_page(self._root, author, post_id, folder)

    def get_marks(self, author: str, post_id: str) -> PostMarks | None:
        """Read validated canonical marks, independent of cached indexed values."""
        with _reading_library():
            root = self._canonical_root()
            return JsonPostMarks(root).get_marks(author, post_id)

    def save_marks(self, author: str, post_id: str, marks: PostMarks) -> None:
        """Persist marks first; a failed projection update leaves canonical marks saved."""
        with self._mutation_lock:
            root = self._canonical_root()
            JsonPostMarks(root).save_marks(author, post_id, marks)
            source = _saved_source(root, author, post_id)
            self._index.upsert_post(project_post(source))

    def set_seen(
        self, author: str, post_id: str, *, seen: bool
    ) -> PostMarkResult | None:
        """Acknowledge current content while preserving other user marks."""
        with writing_marks(), self._mutation_lock:
            return self._mutations.set_seen(author, post_id, seen=seen)

    def set_favorite(
        self, author: str, post_id: str, *, favorite: bool
    ) -> PostMarkResult | None:
        """Change favorite state without replacing seen or playback marks."""
        with writing_marks(), self._mutation_lock:
            return self._mutations.set_favorite(author, post_id, favorite=favorite)

    def set_seen_many(
        self,
        author: str,
        filters: PostFilters,
        *,
        seen: bool,
        progress: Callable[[BulkMarkProgress], None] | None = None,
    ) -> int | None:
        """Update a fixed filtered selection with progress after each durable change."""
        with writing_marks(), self._mutation_lock:
            return self._mutations.set_seen_many(
                author, filters, seen=seen, progress=progress
            )

    def set_position(
        self,
        author: str,
        identity: MediaIdentity,
        seconds: float,
        duration: float,
    ) -> LibraryMediaItem | None:
        """Save progress for a retained playable piece independently of post marks."""
        with writing_marks(), self._mutation_lock:
            return self._mutations.set_position(author, identity, seconds, duration)

    def _canonical_root(self) -> Path:
        with self._index.connect():
            return self._root.resolve()


@contextmanager
def _reading_library() -> Generator[None]:
    try:
        yield
    except (
        OSError,
        ValueError,
        IndexNotPreparedError,
        SQLAlchemyError,
        SQLiteError,
    ) as error:
        message = 'The library data could not be read'
        raise LibraryReadError(message) from error


def _read_details(
    root: Path, author: str, post_id: str, folder: str | None
) -> LibraryPostDetails | None:
    locked = read_locked_posts(root, author).get(post_id)
    if folder is not None:
        source = read_post_source(root, folder, locked_post=locked)
        if source is not None:
            _check_identity(source, author, post_id)
            return _details(source)
    return _details(locked_post_source(root, locked)) if locked is not None else None


def _details(source: PostSource) -> LibraryPostDetails:
    return LibraryPostDetails(source.post, source.marks, source.cover_path)


def _page_folder(author: str, relative: str) -> str | None:
    path = PurePosixPath(relative)
    if (
        len(path.parts) != _AUTHOR_PAGE_DEPTH
        or path.is_absolute()
        or path.as_posix() != relative
        or path.name != _SAVED_PAGE_NAME
        or path.parts[0] in {'.', '..'}
    ):
        return None
    return (PurePosixPath(author) / path.parent).as_posix()


def _read_saved_page(
    root: Path, author: str, post_id: str, folder: str
) -> SavedPage | None:
    source = read_post_source(root, folder)
    if source is None or source.post.record is None:
        return None
    record = source.post.record
    if record.post.author != author or record.post.id != post_id:
        return None
    if record.sync.page_template is None or _inventory_claims_page(record):
        return None
    return SavedPage(folder, (PurePosixPath(folder) / _SAVED_PAGE_NAME).as_posix())


def _inventory_claims_page(record: StoredPost) -> bool:
    return any(
        _is_page_alias(path)
        for entry in record.media.values()
        for path in (entry.path, entry.preview_path)
        if path is not None
    )


def _is_page_alias(path: str) -> bool:
    return (
        '/' not in path
        and path.split(':', 1)[0].rstrip(' .').casefold() == _SAVED_PAGE_NAME
    )


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
