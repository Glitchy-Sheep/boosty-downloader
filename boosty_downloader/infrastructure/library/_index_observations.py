"""Atomic access updates and the completeness of their whole-file projection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from sqlalchemy import select

from boosty_downloader.infrastructure.library._index_models import IndexAuthor
from boosty_downloader.infrastructure.library._index_writes import (
    delete_post,
    refresh_author_counts,
    write_author,
    write_posts,
)
from boosty_downloader.infrastructure.library.index_sources import SourceFingerprint

if TYPE_CHECKING:
    from sqlalchemy import Connection

    from boosty_downloader.infrastructure.library.index_projection import (
        AuthorProjection,
        PostProjection,
    )


@dataclass(frozen=True, slots=True)
class _LockedSourceState:
    fingerprint: SourceFingerprint | None
    synced: bool


def _read_locked_state(
    connection: Connection, author: str
) -> _LockedSourceState | None:
    row = connection.execute(
        select(
            IndexAuthor.locked_json_mtime_ns,
            IndexAuthor.locked_json_size,
            IndexAuthor.locked_json_synced,
        ).where(IndexAuthor.author == author)
    ).one_or_none()
    if row is None:
        return None
    fingerprint = None
    if row.locked_json_mtime_ns is not None and row.locked_json_size is not None:
        fingerprint = SourceFingerprint(row.locked_json_mtime_ns, row.locked_json_size)
    return _LockedSourceState(fingerprint, row.locked_json_synced)


def write_author_metadata(connection: Connection, author: AuthorProjection) -> None:
    """Leave the independent access projection's version and completeness intact."""
    state = _read_locked_state(connection, author.author)
    if state is None:
        state = _LockedSourceState(None, author.locked_fingerprint is None)
    write_author(
        connection,
        replace(author, locked_fingerprint=state.fingerprint),
        locked_synced=state.synced,
    )


def write_access_update(
    connection: Connection,
    author: AuthorProjection,
    post_id: str,
    post: PostProjection | None,
    *,
    previous_locked_fingerprint: SourceFingerprint | None,
) -> None:
    """Keep access rows and the completeness marker in the same transaction."""
    if post is not None and (
        post.metadata.author != author.author or post.metadata.id != post_id
    ):
        message = 'Access projection belongs to another post'
        raise ValueError(message)
    state = _read_locked_state(connection, author.author)
    synced = _can_advance(state, previous_locked_fingerprint, author.locked_fingerprint)
    write_author(connection, author, locked_synced=synced)
    if post is None:
        delete_post(connection, author.author, post_id)
    else:
        write_posts(connection, [post])
    refresh_author_counts(connection, author=author.author)


def _can_advance(
    state: _LockedSourceState | None,
    previous: SourceFingerprint | None,
    current: SourceFingerprint | None,
) -> bool:
    if state is None:
        return previous is None
    return state.synced and state.fingerprint in (previous, current)
