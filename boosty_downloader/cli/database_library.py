"""Prepare explicit C-storage lifetimes independently of network and CLI reporters."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library.db_initialization import (
    initialize_database_library,
)
from boosty_downloader.infrastructure.library.db_library_format import (
    inspect_database_library,
)
from boosty_downloader.infrastructure.library.db_post_records import DatabasePostRecords
from boosty_downloader.infrastructure.library.db_post_store import DatabasePostStore
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase
from boosty_downloader.infrastructure.library.empty_post_locator import EmptyPostLocator

if TYPE_CHECKING:
    from collections.abc import Generator

    from boosty_downloader.application.ports import PostLocator, PostStore
    from boosty_downloader.infrastructure.library.db_library_format import (
        DatabaseLibraryPaths,
    )


@contextmanager
def prepare_database_download(
    paths: DatabaseLibraryPaths,
) -> Generator[PostStore, None, None]:
    """Yield writable records only after owned initialization and one pre-change backup."""
    library_id = initialize_database_library(paths)
    with LibraryDatabase.open(
        paths.database,
        writable=True,
        expected_library_id=library_id,
        backup_before_write=True,
    ) as database:
        yield DatabasePostStore(paths.root, database)


@contextmanager
def prepare_database_preview(
    paths: DatabaseLibraryPaths,
) -> Generator[PostLocator, None, None]:
    """
    Keep user trees unchanged while planning from one private database snapshot.

    Temporary snapshot files and their SQLite sidecars are allowed only in the private temporary directory, which is removed on exit. A new empty destination needs no database or SQLite runtime probe. Pending initialization must be completed by a writable run first.
    """
    inspection = inspect_database_library(paths)
    if inspection.initialization is not None:
        message = f'Library initialization is unfinished: {paths.initialization}. Complete a writable download preparation before previewing it.'
        raise LibraryDatabaseError(message)
    if inspection.marker is None:
        yield EmptyPostLocator(paths.root)
        return
    with LibraryDatabase.preview_snapshot(
        paths.database, expected_library_id=inspection.marker.library_id
    ) as database:
        yield DatabasePostRecords(paths.root, database)
