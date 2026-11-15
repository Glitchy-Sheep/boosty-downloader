"""Spawn-safe probes for a writer interrupted after flush and before commit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from sqlalchemy import event, select, text

from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.library._db_models import DbMarks
from boosty_downloader.infrastructure.library.db_post_records import DatabasePostRecords
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase

if TYPE_CHECKING:
    from multiprocessing.connection import Connection as ProcessConnection
    from multiprocessing.synchronize import Event

    from sqlalchemy import Connection

    from boosty_downloader.domain.library import LocatedPost
    from boosty_downloader.domain.stored_post import StoredPost

COMMITTED_TERM = 'durabletoken'
INTERRUPTED_TERM = 'interruptedtoken'


@dataclass(frozen=True, slots=True)
class SaveRequest:
    root: Path
    database_path: Path
    folder: str
    record: StoredPost


@dataclass(frozen=True, slots=True)
class MediaObservation:
    status: MediaStatus
    path: str | None
    size: int | None


@dataclass(frozen=True, slots=True)
class ProjectionObservation:
    row_id: int
    title: str
    body: str
    tags: list[str]
    media: dict[str, MediaObservation]
    committed_matches: list[int]
    interrupted_matches: list[int]


@dataclass(frozen=True, slots=True)
class LibraryObservation:
    located: LocatedPost | None
    projection: ProjectionObservation
    integrity: str
    favorite: bool | None


def pause_before_commit(
    request: SaveRequest, channel: ProcessConnection, release: Event
) -> None:
    with (
        channel,
        LibraryDatabase.open(request.database_path, writable=True) as database,
    ):
        store = DatabasePostRecords(request.root, database)

        def observe_flushed(connection: Connection) -> None:
            channel.send(_read_projection(connection))
            if not release.wait(timeout=30):
                message = 'Interrupted writer was not terminated within its deadline'
                raise TimeoutError(message)

        event.listen(database.engine, 'commit', observe_flushed)
        store.save_post(request.folder, request.record)


def pause_before_publication(
    request: SaveRequest,
    channel: ProcessConnection,
    release: Event,
) -> None:
    original_mkdir = Path.mkdir
    with (
        channel,
        LibraryDatabase.open(request.database_path, writable=True) as database,
    ):

        def observe_mkdir(
            path: Path,
            mode: int = 0o777,
            *,
            parents: bool = False,
            exist_ok: bool = False,
        ) -> None:
            if path == request.root / request.folder:
                with database.engine.connect() as connection:
                    channel.send(_read_projection(connection))
                if not release.wait(timeout=30):
                    message = 'Publication probe was not terminated within its deadline'
                    raise TimeoutError(message)
            original_mkdir(path, mode, parents=parents, exist_ok=exist_ok)

        with patch.object(Path, 'mkdir', observe_mkdir):
            DatabasePostRecords(request.root, database).save_post(
                request.folder, request.record
            )


def read_restarted_library(request: SaveRequest, channel: ProcessConnection) -> None:
    with channel, LibraryDatabase.open(request.database_path) as database:
        located = DatabasePostRecords(request.root, database).find_post(
            request.record.post.author, request.record.post.id
        )
        with database.engine.connect() as connection:
            observation = LibraryObservation(
                located=located,
                projection=_read_projection(connection),
                integrity=str(
                    connection.execute(text('PRAGMA quick_check')).scalar_one()
                ),
                favorite=connection.execute(
                    select(DbMarks.favorite)
                ).scalar_one_or_none(),
            )
        channel.send(observation)


def _read_projection(connection: Connection) -> ProjectionObservation:
    row = (
        connection.execute(text('SELECT id, title, body_text FROM posts'))
        .mappings()
        .one()
    )
    return ProjectionObservation(
        row_id=int(row['id']),
        title=str(row['title']),
        body=str(row['body_text']),
        tags=list(
            connection.execute(text('SELECT tag FROM post_tags ORDER BY tag')).scalars()
        ),
        media=_read_media(connection),
        committed_matches=_search(connection, COMMITTED_TERM),
        interrupted_matches=_search(connection, INTERRUPTED_TERM),
    )


def _read_media(connection: Connection) -> dict[str, MediaObservation]:
    rows = connection.execute(
        text('SELECT media_id, status, path, size FROM media')
    ).mappings()
    return {
        str(row['media_id']): MediaObservation(
            MediaStatus(row['status']), row['path'], row['size']
        )
        for row in rows
    }


def _search(connection: Connection, term: str) -> list[int]:
    return list(
        connection.execute(
            text('SELECT rowid FROM posts_fts WHERE posts_fts MATCH :term'),
            {'term': term},
        ).scalars()
    )
