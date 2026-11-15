"""Canonical mark changes followed by disposable index repair."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import partial
from pathlib import PurePosixPath
from sqlite3 import Error as SQLiteError
from typing import TYPE_CHECKING, cast

from sqlalchemy.exc import SQLAlchemyError

from boosty_downloader.domain.library import LibraryPostDetails, PostAccess
from boosty_downloader.domain.library_errors import (
    LibraryMarkConflictError,
    LibraryWriteError,
)
from boosty_downloader.domain.library_media import LibraryMediaItem
from boosty_downloader.domain.library_mutations import (
    BulkMarkProgress,
    PostMarkResult,
)
from boosty_downloader.domain.library_summary import (
    latest_media_added_at,
    summarize_post,
)
from boosty_downloader.domain.mark_transitions import (
    mark_favorite,
    mark_position,
    mark_seen,
)
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.infrastructure.library._atomic_write import write_atomically
from boosty_downloader.infrastructure.library._index_models import IndexPost
from boosty_downloader.infrastructure.library._reader_authors import (
    has_author,
    read_author,
)
from boosty_downloader.infrastructure.library._reader_queries import (
    posts_query,
    read_post_location,
)
from boosty_downloader.infrastructure.library._record_paths import check_containment
from boosty_downloader.infrastructure.library._viewer_json import encode_viewer_record
from boosty_downloader.infrastructure.library.author_records import read_locked_posts
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError
from boosty_downloader.infrastructure.library.index import IndexNotPreparedError
from boosty_downloader.infrastructure.library.index_sources import read_post_source
from boosty_downloader.infrastructure.library.post_marks import VIEWER_RECORD_FILENAME

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from boosty_downloader.domain.library import PostFilters
    from boosty_downloader.domain.library_marks import PostMarks
    from boosty_downloader.domain.library_media import MediaIdentity
    from boosty_downloader.domain.stored_post import MediaEntry
    from boosty_downloader.infrastructure.library.index import LibraryIndex
    from boosty_downloader.infrastructure.library.index_sources import PostSource


@dataclass(frozen=True, slots=True)
class _SelectedPost:
    post_id: str
    folder: str


class _MissingMarkSourceError(RuntimeError):
    """A previously validated source disappeared during a mark update."""


def current_time() -> datetime:
    """Use UTC for canonical viewing times."""
    return datetime.now(timezone.utc)


@contextmanager
def writing_marks() -> Generator[None]:
    """Expose expected storage failures without turning programming errors into conflicts."""
    try:
        yield
    except (
        OSError,
        ValueError,
        _MissingMarkSourceError,
        IndexNotPreparedError,
        SQLAlchemyError,
        SQLiteError,
    ) as error:
        message = 'The library marks could not be saved'
        raise LibraryWriteError(message) from error


class JsonMarkMutations:
    """Mutate known saved folders; the reader serializes calls to this adapter."""

    def __init__(
        self, root: Path, index: LibraryIndex, clock: Callable[[], datetime]
    ) -> None:
        self._root = root
        self._index = index
        self._clock = clock

    def set_seen(
        self, author: str, post_id: str, *, seen: bool
    ) -> PostMarkResult | None:
        source = self._post_change(
            author, post_id, partial(_seen, seen=seen, now=self._clock())
        )
        return self._result(author, source) if source is not None else None

    def set_favorite(
        self, author: str, post_id: str, *, favorite: bool
    ) -> PostMarkResult | None:
        source = self._post_change(
            author, post_id, lambda post: mark_favorite(post.marks, favorite=favorite)
        )
        return self._result(author, source) if source is not None else None

    def _post_change(
        self, author: str, post_id: str, transition: Callable[[PostSource], PostMarks]
    ) -> PostSource | None:
        source = self._source(author, post_id)
        if source is None:
            return None
        if source.post.overview.access is PostAccess.locked:
            message = 'Locked posts cannot change seen or favorite marks'
            raise LibraryMarkConflictError(message)
        return self._persist(source, transition(source))

    def set_position(
        self, author: str, identity: MediaIdentity, seconds: float, duration: float
    ) -> LibraryMediaItem | None:
        source = self._source(author, identity.post_id, missing_body_conflict=False)
        if source is None or source.post.record is None:
            return None
        entry = source.post.record.media.get(identity.media_id)
        if entry is None:
            return None
        if (
            entry.kind
            not in {MediaKind.boosty_video, MediaKind.external_video, MediaKind.audio}
            or entry.status is not MediaStatus.downloaded
        ):
            message = 'Only downloaded video or audio can save playback'
            raise LibraryMarkConflictError(message)
        marks = mark_position(
            source.marks, identity.media_id, seconds, duration, now=self._clock()
        )
        return _media_item(self._persist(source, marks), identity.media_id)

    def set_seen_many(
        self,
        author: str,
        filters: PostFilters,
        *,
        seen: bool,
        progress: Callable[[BulkMarkProgress], None] | None,
    ) -> int | None:
        selected = self._selection(author, filters)
        if selected is None:
            return None
        now, changed = self._clock(), 0
        _report(progress, len(selected), 0, changed)
        for completed, item in enumerate(selected, 1):
            changed += self._mark_selected(author, item, seen=seen, now=now)
            _report(progress, len(selected), completed, changed)
        return changed

    def _selection(
        self, author: str, filters: PostFilters
    ) -> list[_SelectedPost] | None:
        with self._index.connect() as connection:
            if not has_author(connection, author):
                return None
            query = (
                posts_query(author, filters)
                .with_only_columns(
                    IndexPost.post_id, IndexPost.folder, maintain_column_froms=True
                )
                .where(
                    IndexPost.access == PostAccess.open.value,
                    IndexPost.folder.is_not(None),
                )
            )
            return [
                _SelectedPost(post_id, cast('str', folder))
                for post_id, folder in connection.execute(query)
            ]

    def _mark_selected(
        self, author: str, selected: _SelectedPost, *, seen: bool, now: datetime
    ) -> int:
        with self._index.connect():
            root = self._root.resolve()
        source = _saved_source(root, author, selected.post_id, selected.folder)
        if source is None or source.post.overview.access is PostAccess.locked:
            return 0
        marks = _seen(source, seen=seen, now=now)
        changed = marks != source.marks
        self._persist(source, marks)
        return int(changed)

    def _source(
        self, author: str, post_id: str, *, missing_body_conflict: bool = True
    ) -> PostSource | None:
        with self._index.connect() as connection:
            indexed = read_post_location(connection, author, post_id)
            root = self._root.resolve()
        if indexed is None:
            return None
        if indexed.folder is None:
            if missing_body_conflict:
                message = 'The post has no saved body for viewing marks'
                raise LibraryMarkConflictError(message)
            return None
        source = _saved_source(root, author, post_id, indexed.folder)
        if (
            source is None
            and missing_body_conflict
            and post_id in read_locked_posts(root, author)
        ):
            message = 'The locked post has no saved body for viewing marks'
            raise LibraryMarkConflictError(message)
        return source

    def _persist(self, source: PostSource, marks: PostMarks) -> PostSource:
        folder = source.post.folder
        metadata = source.post.overview.post
        if folder is None:
            message = 'The post has no saved folder'
            raise LibraryMarkConflictError(message)
        if marks != source.marks:
            root = self._root.resolve()
            path = root / folder / VIEWER_RECORD_FILENAME
            check_containment(root, path)
            write_atomically(
                path, encode_viewer_record(metadata.author, metadata.id, marks)
            )
            refreshed = _saved_source(root, metadata.author, metadata.id, folder)
            if refreshed is None:
                message = 'The saved post disappeared while updating marks'
                raise _MissingMarkSourceError(message)
            source = refreshed
        self._index.update_marks(source)
        return source

    def _result(self, author: str, source: PostSource) -> PostMarkResult:
        with self._index.connect() as connection:
            summary = read_author(connection, author)
        if summary is None:
            message = 'The author disappeared while updating marks'
            raise _MissingMarkSourceError(message)
        detail = LibraryPostDetails(source.post, source.marks, source.cover_path)
        return PostMarkResult(summarize_post(detail), summary)


def _saved_source(
    root: Path, author: str, post_id: str, folder: str
) -> PostSource | None:
    locked = read_locked_posts(root, author).get(post_id)
    source = read_post_source(root, folder, locked_post=locked)
    if source is None:
        return None
    metadata = source.post.overview.post
    if metadata.author != author or metadata.id != post_id:
        message = 'The saved folder belongs to another post'
        raise InvalidPostRecordError(message)
    return source


def _seen(source: PostSource, *, seen: bool, now: datetime) -> PostMarks:
    entries = (
        source.post.record.media.values() if source.post.record is not None else ()
    )
    return mark_seen(
        source.marks, seen=seen, now=now, latest_added_at=latest_media_added_at(entries)
    )


def _media_item(source: PostSource, media_id: str) -> LibraryMediaItem:
    if source.post.record is None or source.post.folder is None:
        message = 'The saved media disappeared while updating its position'
        raise _MissingMarkSourceError(message)
    entry = source.post.record.media.get(media_id)
    if entry is None:
        message = 'The saved media disappeared while updating its position'
        raise _MissingMarkSourceError(message)
    post = source.post.overview.post
    return LibraryMediaItem(
        post.id,
        post.created_at,
        source.post.folder,
        media_id,
        entry,
        source.marks.positions.get(media_id),
        _playback_thumbnail(source.post.folder, entry),
    )


def _playback_thumbnail(folder: str, entry: MediaEntry) -> str | None:
    if (
        entry.kind in {MediaKind.boosty_video, MediaKind.external_video}
        and entry.preview_path is not None
    ):
        return (PurePosixPath(folder) / entry.preview_path).as_posix()
    return None


def _report(
    callback: Callable[[BulkMarkProgress], None] | None,
    total: int,
    completed: int,
    changed: int,
) -> None:
    if callback is not None:
        callback(BulkMarkProgress(total, completed, changed))
