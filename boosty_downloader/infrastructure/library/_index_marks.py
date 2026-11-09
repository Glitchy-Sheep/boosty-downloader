"""Refresh marks without rewriting unchanged post content and search rows."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import bindparam, select, update

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from boosty_downloader.domain.library_marks import PostMarks
    from boosty_downloader.infrastructure.library._index_writes import SqlValues
    from boosty_downloader.infrastructure.library.index_sources import PostSource


def write_marks_if_current(connection: Connection, source: PostSource) -> bool:
    """Update an unchanged open post; other sources need a complete projection."""
    row_id = _current_open_post_id(connection, source)
    if row_id is None:
        return False
    _write_post_marks(connection, row_id, source)
    _write_positions(connection, row_id, source.marks)
    return True


def _current_open_post_id(connection: Connection, source: PostSource) -> int | None:
    fingerprint = source.record_fingerprint
    if source.post.overview.access is not PostAccess.open or fingerprint is None:
        return None
    post = source.post.overview.post
    return connection.scalar(
        select(IndexPost.id).where(
            IndexPost.author == post.author,
            IndexPost.post_id == post.id,
            IndexPost.folder == source.post.folder,
            IndexPost.access == PostAccess.open.value,
            IndexPost.post_json_mtime_ns == fingerprint.mtime_ns,
            IndexPost.post_json_size == fingerprint.size,
        )
    )


def _write_post_marks(connection: Connection, row_id: int, source: PostSource) -> None:
    marks = source.marks_fingerprint
    mtime = marks.mtime_ns if marks is not None else None
    size = marks.size if marks is not None else None
    connection.execute(
        update(IndexPost)
        .where(IndexPost.id == row_id)
        .values(
            seen_at=source.marks.seen_at,
            favorite=source.marks.favorite,
            viewer_json_mtime_ns=mtime,
            viewer_json_size=size,
            cover_path=source.cover_path,
        )
    )


def _write_positions(
    connection: Connection, post_row_id: int, marks: PostMarks
) -> None:
    connection.execute(
        update(IndexMedia)
        .where(IndexMedia.post_row_id == post_row_id)
        .values(playback_position=None, finished_at=None)
    )
    if not marks.positions:
        return
    values: list[SqlValues] = [
        {
            'mark_media_id': media_id,
            'mark_position': position.seconds,
            'mark_finished_at': position.finished_at,
        }
        for media_id, position in marks.positions.items()
    ]
    connection.execute(
        update(IndexMedia)
        .where(
            IndexMedia.post_row_id == post_row_id,
            IndexMedia.media_id == bindparam('mark_media_id'),
        )
        .values(
            playback_position=bindparam('mark_position'),
            finished_at=bindparam('mark_finished_at'),
        ),
        values,
    )
