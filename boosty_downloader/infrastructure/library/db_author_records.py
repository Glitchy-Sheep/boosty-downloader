"""Atomic author snapshots and access observations in the primary library."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import select

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.stored_post import AuthorInfo, LockedPost, PostMetadata
from boosty_downloader.infrastructure.library._author_validation import (
    author_validation_message,
    validate_author_snapshot,
    validate_locked_snapshot,
)
from boosty_downloader.infrastructure.library._db_locked_post import read_locked_post
from boosty_downloader.infrastructure.library._db_models import (
    DbAuthor,
    DbMarks,
    DbMediaMarks,
    DbPost,
)
from boosty_downloader.infrastructure.library._db_post_mapping import (
    update_post_overview,
)
from boosty_downloader.infrastructure.library._db_post_paths import author_directory
from boosty_downloader.infrastructure.library._db_records import (
    ensure_author,
    find_post_row,
    read_session,
    require_author_identity,
    synchronize_post_tags,
)
from boosty_downloader.infrastructure.library._record_validation import require_identity
from boosty_downloader.infrastructure.library.errors import InvalidAuthorRecordError

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from sqlalchemy.orm import Session

    from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


class DatabaseAuthorRecords:
    """Borrow a ready database for metadata operations without creating asset folders."""

    def __init__(self, root: Path, database: LibraryDatabase) -> None:
        self._root = root.resolve()
        self._database = database

    def load_author(self, author: str) -> AuthorInfo | None:
        """Read a detached author snapshot; an identity placeholder has no snapshot."""
        author_directory(self._root, author)
        with self._session(writable=False) as session:
            require_author_identity(session, author)
            row = session.get(DbAuthor, author)
            return _read_author(row) if row is not None else None

    def save_author(self, author: AuthorInfo) -> None:
        """Replace all author metadata, including explicitly cleared image references."""
        author = validate_author_snapshot(author)
        author_directory(self._root, author.author)
        with self._session(writable=True) as session:
            require_author_identity(session, author.author)
            row = ensure_author(session, author.author)
            _read_author(row)
            _update_author(row, author)

    def load_locked_post(self, author: str, post_id: str) -> LockedPost | None:
        """Read the current access overview independently of retained saved metadata."""
        self._validate_identity(author, post_id)
        with self._session(writable=False) as session:
            require_author_identity(session, author)
            row = find_post_row(session, author, post_id)
            if row is None or row.access != PostAccess.locked:
                return None
            return read_locked_post(row)

    def save_locked_post(self, post: LockedPost) -> None:
        """Update one access observation while retaining saved content and all marks."""
        post = validate_locked_snapshot(post)
        self._validate_identity(post.post.author, post.post.id)
        with self._session(writable=True) as session:
            require_author_identity(session, post.post.author)
            ensure_author(session, post.post.author)
            row = find_post_row(session, post.post.author, post.post.id)
            if row is None:
                row = DbPost(author=post.post.author, post_id=post.post.id)
                session.add(row)
            elif row.access == PostAccess.locked:
                read_locked_post(row)
            _update_locked(row, post)
            session.flush()
            synchronize_post_tags(session, row)

    def clear_locked_post(self, author: str, post_id: str) -> None:
        """Restore the saved overview, or remove an unsaved observation without marks."""
        self._validate_identity(author, post_id)
        with self._session(writable=True) as session:
            require_author_identity(session, author)
            row = find_post_row(session, author, post_id)
            if row is None or row.access != PostAccess.locked:
                return
            read_locked_post(row)
            if row.saved_metadata is None:
                _require_no_marks(session, row.id)
                session.delete(row)
                return
            _restore_saved_overview(row, row.saved_metadata)
            synchronize_post_tags(session, row)

    def _validate_identity(self, author: str, post_id: str) -> None:
        author_directory(self._root, author)
        require_identity(post_id, 'post ID')

    @contextmanager
    def _session(self, *, writable: bool) -> Generator[Session, None, None]:
        manager = (
            self._database.transaction() if writable else read_session(self._database)
        )
        try:
            with manager as session:
                yield session
        except ValidationError as error:
            raise InvalidAuthorRecordError(author_validation_message(error)) from None


def _read_author(row: DbAuthor) -> AuthorInfo | None:
    if row.synced_at is None:
        _require_empty_placeholder(row)
        return None
    return validate_author_snapshot(
        AuthorInfo(
            author=row.author,
            synced_at=row.synced_at,
            title=row.title,
            owner_name=row.owner_name,
            description=row.description,
            avatar_path=row.avatar_path,
            cover_path=row.cover_path,
            remote_post_count=row.remote_post_count,
        )
    )


def _require_empty_placeholder(row: DbAuthor) -> None:
    values = [
        row.title,
        row.owner_name,
        row.description,
        row.avatar_path,
        row.cover_path,
        row.remote_post_count,
    ]
    if any(value is not None for value in values):
        message = 'Author metadata has no synchronization time'
        raise InvalidAuthorRecordError(message)


def _update_author(row: DbAuthor, info: AuthorInfo) -> None:
    row.title = info.title
    row.owner_name = info.owner_name
    row.description = info.description
    row.avatar_path = info.avatar_path
    row.cover_path = info.cover_path
    row.synced_at = info.synced_at
    row.remote_post_count = info.remote_post_count


def _update_locked(row: DbPost, post: LockedPost) -> None:
    update_post_overview(row, post.post)
    row.access = PostAccess.locked
    row.locked_synced_at = post.synced_at
    row.teaser_path = post.teaser_path
    row.teaser_thumbnail_path = post.teaser_thumbnail_path


def _restore_saved_overview(row: DbPost, saved: PostMetadata) -> None:
    if saved.author != row.author or saved.id != row.post_id:
        message = 'Saved metadata disagrees with the post identity'
        raise InvalidAuthorRecordError(message)
    update_post_overview(row, saved)
    row.access = PostAccess.open
    row.locked_synced_at = None
    row.teaser_path = None
    row.teaser_thumbnail_path = None


def _require_no_marks(session: Session, post_row_id: int) -> None:
    marks = session.scalar(
        select(DbMarks.post_row_id).where(DbMarks.post_row_id == post_row_id)
    )
    playback = session.scalar(
        select(DbMediaMarks.post_row_id)
        .where(DbMediaMarks.post_row_id == post_row_id)
        .limit(1)
    )
    if marks is not None or playback is not None:
        message = 'Cannot remove a locked-only post with saved user marks'
        raise InvalidAuthorRecordError(message)
