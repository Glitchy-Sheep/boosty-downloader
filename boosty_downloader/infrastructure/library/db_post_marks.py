"""Atomic full snapshots of user viewing marks in the primary database."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from pydantic import ValidationError
from sqlalchemy import delete, select, type_coerce
from sqlalchemy.types import NullType

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.infrastructure.library._db_locked_post import read_locked_post
from boosty_downloader.infrastructure.library._db_models import (
    DbMarks,
    DbMediaMarks,
    DbPost,
)
from boosty_downloader.infrastructure.library._db_post_paths import author_directory
from boosty_downloader.infrastructure.library._db_records import (
    find_post_row,
    read_session,
    require_author_identity,
)
from boosty_downloader.infrastructure.library._db_saved_post import read_saved_location
from boosty_downloader.infrastructure.library._marks_validation import (
    validate_marks_snapshot,
)
from boosty_downloader.infrastructure.library._record_validation import (
    require_identity,
    validate_temporal_text,
)
from boosty_downloader.infrastructure.library._stored_validation import (
    validation_message,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidPostRecordError,
    InvalidViewerRecordError,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from sqlalchemy.orm import Session

    from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


class DatabasePostMarks:
    """
    Borrow a ready database for independent mark snapshots and complete replacements.

    A missing saved folder hides its entire generation, including unreadable marks. Only the next post save resets those rows; mark operations leave them unchanged.
    """

    def __init__(self, root: Path, database: LibraryDatabase) -> None:
        self._root = root.resolve()
        self._database = database

    def get_marks(self, author: str, post_id: str) -> PostMarks | None:
        """Read marks only for a confirmed generation, or defaults for a locked overview."""
        self._validate_identity(author, post_id)
        with self._session(writable=False) as session:
            require_author_identity(session, author)
            row = find_post_row(session, author, post_id)
            if row is None:
                return None
            if read_saved_location(session, self._root, row) is not None:
                return _read_marks(session, row.id)
            _require_consistent_unsaved_marks(session, row)
            if row.access == PostAccess.locked:
                read_locked_post(row)
                return PostMarks()
            return None

    def save_marks(self, author: str, post_id: str, marks: PostMarks) -> None:
        """Replace a complete snapshot in one transaction; omitted positions are removed."""
        marks = validate_marks_snapshot(marks)
        self._validate_identity(author, post_id)
        with self._session(writable=True) as session:
            require_author_identity(session, author)
            row = find_post_row(session, author, post_id)
            if row is not None:
                _require_consistent_unsaved_marks(session, row)
            if row is None or read_saved_location(session, self._root, row) is None:
                message = f'No confirmed saved folder for {author}/{post_id}'
                raise LookupError(message)
            _read_marks(session, row.id)
            _replace_marks(session, row.id, marks)

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
            raise InvalidPostRecordError(validation_message(error)) from None


def _require_consistent_unsaved_marks(session: Session, post: DbPost) -> None:
    if post.saved_metadata is not None:
        return
    scalar = session.scalar(
        select(DbMarks.post_row_id).where(DbMarks.post_row_id == post.id)
    )
    playback = session.scalar(
        select(DbMediaMarks.post_row_id)
        .where(DbMediaMarks.post_row_id == post.id)
        .limit(1)
    )
    if scalar is not None or playback is not None:
        message = 'User marks belong to a post without a saved generation'
        raise InvalidViewerRecordError(message)


def _read_marks(session: Session, post_row_id: int) -> PostMarks:
    # Raw values retain corruption evidence that Boolean and numeric readers can erase.
    row = (
        session.execute(
            select(
                type_coerce(DbMarks.seen_at, NullType).label('seen_at'),
                type_coerce(DbMarks.favorite, NullType).label('favorite'),
            ).where(DbMarks.post_row_id == post_row_id)
        )
        .mappings()
        .one_or_none()
    )
    positions = _read_positions(session, post_row_id)
    if row is None:
        return validate_marks_snapshot(PostMarks(positions=positions))
    return validate_marks_snapshot(
        PostMarks(
            seen_at=_read_timestamp(row['seen_at']),
            favorite=_read_favorite(row['favorite']),
            positions=positions,
        )
    )


def _read_positions(session: Session, post_row_id: int) -> dict[str, PlaybackPosition]:
    rows = session.execute(
        select(
            DbMediaMarks.media_id,
            type_coerce(DbMediaMarks.position, NullType).label('seconds'),
            type_coerce(DbMediaMarks.finished_at, NullType).label('finished_at'),
        ).where(DbMediaMarks.post_row_id == post_row_id)
    ).mappings()
    return {
        row['media_id']: PlaybackPosition(
            row['seconds'], _read_timestamp(row['finished_at'])
        )
        for row in rows
    }


def _read_favorite(value: object) -> bool:
    if type(value) is not int or value not in {0, 1}:
        message = 'Invalid viewer record: favorite must be stored as 0 or 1'
        raise InvalidViewerRecordError(message)
    return value == 1


def _read_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    message = 'Invalid viewer record: malformed stored timestamp'
    if not isinstance(value, str):
        raise InvalidViewerRecordError(message)
    try:
        validate_temporal_text({'seen_at': value})
        normalized = (
            value.removesuffix('Z') + '+00:00' if value.endswith('Z') else value
        )
        timestamp = datetime.fromisoformat(normalized)
        if timestamp.utcoffset() is None:
            # SQLite stores canonical UTC timestamps without an offset.
            return timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise InvalidViewerRecordError(message) from None


def _replace_marks(session: Session, post_row_id: int, marks: PostMarks) -> None:
    row = session.get(DbMarks, post_row_id)
    if row is None:
        row = DbMarks(post_row_id=post_row_id)
        session.add(row)
    row.seen_at = marks.seen_at
    row.favorite = marks.favorite
    session.execute(delete(DbMediaMarks).where(DbMediaMarks.post_row_id == post_row_id))
    session.add_all(
        [
            DbMediaMarks(
                post_row_id=post_row_id,
                media_id=media_id,
                position=position.seconds,
                finished_at=position.finished_at,
            )
            for media_id, position in marks.positions.items()
        ]
    )
