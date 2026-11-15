"""Locate and identify primary SQLite libraries independently of the JSON format."""

from __future__ import annotations

import os
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Final, Literal
from uuid import UUID  # noqa: TC003 - Pydantic resolves marker annotations

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from boosty_downloader.infrastructure.library._db_engine import (
    backup_path,
    backup_sidecars,
    validate_database_path,
    validate_new_database_path,
)
from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library._db_marker_files import (
    read_marker_bytes,
    validate_marker_path,
)

DATABASE_FORMAT_VERSION: Final = 5
_METADATA_DIRECTORY: Final = '.boosty-downloader'
_DATABASE_NAME: Final = 'library.db'
_SIDECAR_SUFFIXES: Final = ('-wal', '-shm', '-journal')


@dataclass(frozen=True, slots=True)
class DatabaseLibraryPaths:
    """One library root and its explicitly selected primary database."""

    root: Path
    database: Path

    @property
    def marker(self) -> Path:
        return self.root / _METADATA_DIRECTORY / 'library.json'

    @property
    def initialization(self) -> Path:
        return self.root / _METADATA_DIRECTORY / 'initialization.json'

    @property
    def location_hash(self) -> str:
        location = os.path.normcase(_absolute_path(self.database))
        return sha256(os.fsencode(location)).hexdigest()


class DatabaseLibraryMarker(BaseModel):
    """Portable ready identity; no machine-specific cache location is stored."""

    model_config = ConfigDict(extra='forbid', frozen=True)

    storage: Literal['sqlite']
    format_version: int = Field(strict=True)
    library_id: UUID


class DatabaseInitialization(DatabaseLibraryMarker):
    """Immutable ownership of one unfinished initialization at one location."""

    database_location: str = Field(pattern=r'^[0-9a-f]{64}$')


@dataclass(frozen=True, slots=True)
class DatabaseLibraryInspection:
    """Ready identity or pending ownership; neither is present for an empty target."""

    marker: DatabaseLibraryMarker | None = None
    initialization: DatabaseInitialization | None = None


def database_library_paths(
    root: Path, cache_dir: Path | None = None
) -> DatabaseLibraryPaths:
    """Select paths without creating directories or resolving symlinked ancestors."""
    root = _absolute_path(root)
    directory = root / _METADATA_DIRECTORY
    if cache_dir is not None:
        directory = _absolute_path(cache_dir)
    return DatabaseLibraryPaths(root, directory / _DATABASE_NAME)


def _absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(path))  # noqa: PTH100 - preserve symlinks for validation


def inspect_database_library(paths: DatabaseLibraryPaths) -> DatabaseLibraryInspection:
    """Refuse incompatible or unowned state before primary database creation."""
    validate_marker_path(paths.marker)
    validate_marker_path(paths.initialization)
    validate_database_path(paths.database)
    _check_metadata_files(paths)
    marker = read_database_marker(paths.marker)
    if marker is not None:
        if not paths.database.is_file():
            message = f'Primary library database is missing: {paths.database}; restore {backup_path(paths.database)}'
            raise LibraryDatabaseError(message)
        return DatabaseLibraryInspection(marker=marker)
    initialization = read_initialization(paths)
    _check_pending_contents(paths)
    if initialization is None:
        validate_new_database_path(paths.database)
        if paths.database.exists():
            message = f'Unmarked primary database cannot be adopted: {paths.database}'
            raise LibraryDatabaseError(message)
    return DatabaseLibraryInspection(initialization=initialization)


def read_database_marker(path: Path) -> DatabaseLibraryMarker | None:
    """Read only an explicit supported SQLite ready marker."""
    data = read_marker_bytes(path)
    if data is None:
        return None
    try:
        marker = DatabaseLibraryMarker.model_validate_json(data)
    except ValidationError as error:
        message = f'Invalid primary SQLite library marker: {path}'
        raise LibraryDatabaseError(message) from error
    _require_format(marker, path)
    return marker


def read_initialization(paths: DatabaseLibraryPaths) -> DatabaseInitialization | None:
    """Accept pending ownership only at the originally selected database location."""
    data = read_marker_bytes(paths.initialization)
    if data is None:
        return None
    try:
        receipt = DatabaseInitialization.model_validate_json(data)
    except ValidationError as error:
        message = f'Invalid library initialization receipt: {paths.initialization}'
        raise LibraryDatabaseError(message) from error
    _require_format(receipt, paths.initialization)
    if receipt.database_location != paths.location_hash:
        message = f'Unfinished library initialization belongs to another database location: {paths.initialization}. Use the original cache directory.'
        raise LibraryDatabaseError(message)
    return receipt


def _require_format(marker: DatabaseLibraryMarker, path: Path) -> None:
    if marker.format_version != DATABASE_FORMAT_VERSION:
        message = f'Unsupported library format {marker.format_version} in {path}; expected {DATABASE_FORMAT_VERSION}'
        raise LibraryDatabaseError(message)


def _database_files(primary: Path) -> set[Path]:
    return {
        primary,
        *(primary.with_name(primary.name + suffix) for suffix in _SIDECAR_SUFFIXES),
        backup_path(primary),
        *backup_sidecars(primary),
    }


def _check_metadata_files(paths: DatabaseLibraryPaths) -> None:
    metadata = paths.marker.parent
    if not metadata.exists():
        return
    allowed = {
        paths.marker,
        paths.initialization,
        *_database_files(paths.database),
        *_database_files(metadata / _DATABASE_NAME),
    }
    allowed.update(
        parent for parent in paths.database.parents if metadata in parent.parents
    )
    for entry in metadata.iterdir():
        if entry not in allowed:
            _unexpected_file(entry)


def _check_pending_contents(paths: DatabaseLibraryPaths) -> None:
    if not paths.root.exists():
        return
    allowed_files = {paths.initialization, *_database_files(paths.database)}
    allowed_directories = {paths.marker.parent}
    allowed_directories.update(
        parent for parent in paths.database.parents if paths.root in parent.parents
    )
    pending = [paths.root]
    while pending:
        for entry in pending.pop().iterdir():
            if entry in allowed_directories:
                pending.append(entry)
            elif entry not in allowed_files:
                _unexpected_file(entry)


def _unexpected_file(path: Path) -> None:
    message = f'Unowned library initialization content must be preserved: {path}. Choose an empty destination or inspect the interrupted initialization.'
    raise LibraryDatabaseError(message)
