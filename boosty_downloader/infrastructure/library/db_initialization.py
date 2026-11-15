"""Complete only proven empty primary-library initialization, preserving conflicts."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Final
from uuid import UUID, uuid4

from sqlalchemy import select, table, text

from boosty_downloader.infrastructure.library._db_engine import (
    DatabaseFileIdentity,
    backup_path,
    backup_sidecars,
    validate_new_database_path,
)
from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library._db_marker_files import publish_marker
from boosty_downloader.infrastructure.library._db_models import DbMeta, LibraryBase
from boosty_downloader.infrastructure.library._db_runtime import (
    require_supported_sqlite,
)
from boosty_downloader.infrastructure.library._db_snapshot import database_snapshot
from boosty_downloader.infrastructure.library.db_library_format import (
    DATABASE_FORMAT_VERSION,
    DatabaseInitialization,
    DatabaseLibraryMarker,
    DatabaseLibraryPaths,
    inspect_database_library,
    read_database_marker,
    read_initialization,
)
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_SEARCH_TABLE: Final = 'posts_fts'


def initialize_database_library(paths: DatabaseLibraryPaths) -> UUID:
    """Create or resume an owned empty library; never recreate an established one."""
    require_supported_sqlite()
    inspection = inspect_database_library(paths)
    if inspection.marker is not None:
        library_id = inspection.marker.library_id
        LibraryDatabase.inspect(paths.database, expected_library_id=library_id)
        return library_id
    receipt = inspection.initialization
    if receipt is None:
        receipt = _claim_initialization(paths)
    _create_or_resume_database(paths, receipt)
    _complete_initialization(paths, receipt)
    return receipt.library_id


def _claim_initialization(paths: DatabaseLibraryPaths) -> DatabaseInitialization:
    receipt = DatabaseInitialization(
        storage='sqlite',
        format_version=DATABASE_FORMAT_VERSION,
        library_id=uuid4(),
        database_location=paths.location_hash,
    )
    try:
        publish_marker(paths.initialization, _record_bytes(receipt))
    except FileExistsError:
        existing = read_initialization(paths)
        if existing is None:
            message = (
                f'Library initialization receipt disappeared: {paths.initialization}'
            )
            raise LibraryDatabaseError(message) from None
        return existing
    return receipt


def _create_or_resume_database(
    paths: DatabaseLibraryPaths, receipt: DatabaseInitialization
) -> None:
    inspection = inspect_database_library(paths)
    if inspection.marker is not None:
        _require_ready_identity(inspection.marker, receipt.library_id)
        return
    _require_receipt(paths, receipt)
    _require_no_pending_backup(paths)
    if not paths.database.exists():
        validate_new_database_path(paths.database)
        with suppress(FileExistsError):
            LibraryDatabase.create(
                paths.database, library_id=receipt.library_id
            ).close()
    _validate_empty_snapshot(paths, receipt.library_id)


def _validate_empty_snapshot(paths: DatabaseLibraryPaths, library_id: UUID) -> None:
    with (
        database_snapshot(paths.database) as snapshot,
        LibraryDatabase.open(snapshot, expected_library_id=library_id) as database,
        database.transaction() as session,
    ):
        _require_empty(session)


def _complete_initialization(
    paths: DatabaseLibraryPaths, receipt: DatabaseInitialization
) -> None:
    source_file = DatabaseFileIdentity.capture(paths.database)
    with (
        LibraryDatabase.open_for_initialization(
            paths.database, expected_library_id=receipt.library_id
        ) as database,
        database.transaction() as session,
    ):
        # Hold the primary write lock even when another initializer is already ready.
        session.connection()
        source_file.require_unchanged(paths.database)
        inspection = inspect_database_library(paths)
        if inspection.marker is not None:
            _require_ready_identity(inspection.marker, receipt.library_id)
            return
        _require_receipt(paths, receipt)
        _require_no_pending_backup(paths)
        _require_empty(session)
        source_file.require_unchanged(paths.database)
        _publish_ready(paths, receipt.library_id)


def _publish_ready(paths: DatabaseLibraryPaths, library_id: UUID) -> None:
    marker = DatabaseLibraryMarker(
        storage='sqlite', format_version=DATABASE_FORMAT_VERSION, library_id=library_id
    )
    try:
        publish_marker(paths.marker, _record_bytes(marker))
    except FileExistsError:
        existing = read_database_marker(paths.marker)
        if existing is None:
            message = f'Ready library marker disappeared: {paths.marker}'
            raise LibraryDatabaseError(message) from None
        _require_ready_identity(existing, library_id)


def _require_ready_identity(marker: DatabaseLibraryMarker, library_id: UUID) -> None:
    if marker.library_id != library_id:
        message = 'A different library published the ready marker during initialization'
        raise LibraryDatabaseError(message)


def _require_receipt(
    paths: DatabaseLibraryPaths, expected: DatabaseInitialization
) -> None:
    if read_initialization(paths) != expected:
        message = f'Library initialization ownership changed: {paths.initialization}'
        raise LibraryDatabaseError(message)


def _require_no_pending_backup(paths: DatabaseLibraryPaths) -> None:
    for candidate in [backup_path(paths.database), *backup_sidecars(paths.database)]:
        if candidate.exists():
            message = f'Unfinished library contains a recovery copy that must be preserved: {candidate}'
            raise LibraryDatabaseError(message)


def _require_empty(session: Session) -> None:
    _require_known_tables(session)
    canonical_tables = [
        candidate
        for candidate in LibraryBase.metadata.sorted_tables
        if candidate is not DbMeta.__table__
    ]
    for candidate in [*canonical_tables, table(_SEARCH_TABLE)]:
        if session.scalar(select(1).select_from(candidate).limit(1)) is not None:
            message = (
                'Unfinished primary library is not empty; preserve its existing records'
            )
            raise LibraryDatabaseError(message)


def _require_known_tables(session: Session) -> None:
    known = {*LibraryBase.metadata.tables, _SEARCH_TABLE}
    with session.scalars(
        text(
            "SELECT name FROM pragma_table_list WHERE schema = 'main' "
            "AND type IN ('table', 'virtual') AND name NOT GLOB 'sqlite_*'"
        )
    ) as tables:
        for name in tables:
            if name not in known:
                message = f'Unfinished primary library contains an unknown table: {name}; preserve its existing state'
                raise LibraryDatabaseError(message)


def _record_bytes(record: DatabaseLibraryMarker) -> bytes:
    return (record.model_dump_json() + '\n').encode()
