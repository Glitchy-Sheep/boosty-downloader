import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import pytest

from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library.db_initialization import (
    initialize_database_library,
)
from boosty_downloader.infrastructure.library.db_library_format import (
    database_library_paths,
    inspect_database_library,
)
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase
from boosty_downloader.infrastructure.library.library_format import (
    LibraryCompatibilityError,
    check_library_compatibility,
    initialize_library,
)


@dataclass(frozen=True, slots=True)
class _FileState:
    data: bytes | None
    modified_ns: int


def _tree(root: Path) -> dict[str, _FileState]:
    return {
        path.relative_to(root).as_posix(): _FileState(
            path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns
        )
        for path in root.rglob('*')
    }


def test_location_selection_is_pure_and_explicit_cache_wins(tmp_path: Path):
    root = tmp_path.resolve() / 'library'
    cache = tmp_path.resolve() / 'cache'
    assert (
        database_library_paths(root).database == root / '.boosty-downloader/library.db'
    )
    assert database_library_paths(root, cache).database == cache / 'library.db'
    assert database_library_paths(root / '..' / 'library').root == root
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    'cache_folder', ['.', 'cache/nested', '.boosty-downloader/cache']
)
def test_explicit_cache_can_be_nested_inside_the_library(
    tmp_path: Path, cache_folder: str
):
    root = tmp_path.resolve() / 'library'
    paths = database_library_paths(root, root / cache_folder)
    library_id = initialize_database_library(paths)
    assert LibraryDatabase.inspect(paths.database).library_id == library_id
    assert initialize_database_library(paths) == library_id


def test_empty_metadata_directory_can_survive_an_interrupted_first_attempt(
    tmp_path: Path,
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    paths.marker.parent.mkdir(parents=True)
    initialize_database_library(paths)
    assert paths.marker.is_file()


@pytest.mark.parametrize('external_cache', [False, True])
def test_new_library_has_one_matching_identity_and_no_recovery_rotation(
    tmp_path: Path, *, external_cache: bool
):
    root = tmp_path.resolve() / 'library'
    cache = tmp_path.resolve() / 'cache' if external_cache else None
    paths = database_library_paths(root, cache)
    library_id = initialize_database_library(paths)
    marker = json.loads(paths.marker.read_bytes())
    receipt = json.loads(paths.initialization.read_bytes())
    assert marker == {
        'storage': 'sqlite',
        'format_version': 5,
        'library_id': str(library_id),
    }
    assert receipt == {**marker, 'database_location': paths.location_hash}
    assert LibraryDatabase.inspect(paths.database).library_id == library_id
    assert not paths.database.with_name('library.db.bak').exists()
    before = _tree(tmp_path)
    assert initialize_database_library(paths) == library_id
    assert _tree(tmp_path) == before


def test_json_and_primary_markers_are_mutually_incompatible(tmp_path: Path):
    json_root = tmp_path.resolve() / 'json'
    initialize_library(json_root)
    before = _tree(tmp_path)
    with pytest.raises(LibraryDatabaseError, match='SQLite library marker'):
        initialize_database_library(database_library_paths(json_root))
    assert _tree(tmp_path) == before
    sqlite_paths = database_library_paths(tmp_path.resolve() / 'sqlite')
    initialize_database_library(sqlite_paths)
    before = _tree(tmp_path)
    with pytest.raises(LibraryCompatibilityError):
        check_library_compatibility(sqlite_paths.root)
    assert _tree(tmp_path) == before


@pytest.mark.parametrize('content', ['legacy-post', 'unknown-metadata', 'orphan-temp'])
def test_unmarked_content_is_preserved_and_not_adopted(tmp_path: Path, content: str):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    match content:
        case 'legacy-post':
            existing = paths.root / 'alice/2026-11-15 Post [12345678]/post.json'
        case 'unknown-metadata':
            existing = paths.marker.parent / 'index.db'
        case _:
            existing = paths.marker.parent / '.initialization.abandoned.tmp'
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'preserved user data')
    before = _tree(tmp_path)
    with pytest.raises(LibraryDatabaseError, match='must be preserved'):
        initialize_database_library(paths)
    assert _tree(tmp_path) == before
    assert not paths.database.exists()


def test_unmarked_primary_is_not_adopted(tmp_path: Path):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    LibraryDatabase.create(paths.database).close()
    before = _tree(tmp_path)
    with pytest.raises(LibraryDatabaseError, match='cannot be adopted'):
        initialize_database_library(paths)
    assert _tree(tmp_path) == before


def test_ready_marker_with_missing_database_never_recreates_it(tmp_path: Path):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    initialize_database_library(paths)
    paths.database.unlink()
    before = _tree(tmp_path)
    with pytest.raises(LibraryDatabaseError, match='missing') as error:
        initialize_database_library(paths)
    assert str(paths.database) in str(error.value)
    assert str(paths.database.with_name('library.db.bak')) in str(error.value)
    assert _tree(tmp_path) == before


def test_ready_library_relocation_ignores_old_receipt_location(tmp_path: Path):
    paths = database_library_paths(tmp_path.resolve() / 'before')
    library_id = initialize_database_library(paths)
    destination = tmp_path.resolve() / 'after'
    paths.root.rename(destination)
    moved = database_library_paths(destination)
    before = _tree(tmp_path)
    assert initialize_database_library(moved) == library_id
    assert _tree(tmp_path) == before


def test_ready_marker_refuses_a_foreign_cache_database_without_changes(tmp_path: Path):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    initialize_database_library(paths)
    foreign = database_library_paths(paths.root, tmp_path.resolve() / 'foreign-cache')
    LibraryDatabase.create(foreign.database).close()
    before = _tree(tmp_path)
    with pytest.raises(LibraryDatabaseError, match='match its marker'):
        initialize_database_library(foreign)
    assert _tree(tmp_path) == before


@pytest.mark.parametrize(
    'damage', ['json-format', 'future', 'partial', 'unknown-field']
)
def test_invalid_marker_is_rejected_before_any_primary_creation(
    tmp_path: Path, damage: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    paths.marker.parent.mkdir(parents=True)
    data: dict[str, object] = {
        'storage': 'sqlite',
        'format_version': 5,
        'library_id': str(uuid4()),
    }
    match damage:
        case 'json-format':
            data = {'format_version': 5}
        case 'future':
            data['format_version'] = 99
        case 'unknown-field':
            data['database_path'] = '/another/library.db'
    paths.marker.write_text('{' if damage == 'partial' else json.dumps(data))
    before = _tree(tmp_path)
    with pytest.raises(LibraryDatabaseError):
        inspect_database_library(paths)
    assert _tree(tmp_path) == before


@pytest.mark.parametrize('filename', ['library.json', 'initialization.json'])
@pytest.mark.parametrize('damage', ['partial', 'oversized', 'shared'])
def test_invalid_ownership_records_are_preserved_without_primary_creation(
    tmp_path: Path, filename: str, damage: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    record = paths.marker.parent / filename
    record.parent.mkdir(parents=True)
    record.write_bytes(b'{' if damage != 'oversized' else b' ' * 4097)
    if damage == 'shared':
        alias = tmp_path / 'record-alias'
        alias.hardlink_to(record)
    before = _tree(tmp_path)
    with pytest.raises(LibraryDatabaseError):
        initialize_database_library(paths)
    assert _tree(tmp_path) == before
    assert not paths.database.exists()


def test_symlinked_metadata_directory_is_not_resolved_into_a_valid_location(
    tmp_path: Path,
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    paths.root.mkdir()
    elsewhere = tmp_path.resolve() / 'elsewhere'
    elsewhere.mkdir()
    try:
        paths.marker.parent.symlink_to(elsewhere, target_is_directory=True)
    except OSError as error:
        pytest.skip(f'Symlink creation is unavailable: {error}')
    with pytest.raises(LibraryDatabaseError, match='ordinary directory'):
        initialize_database_library(paths)
    assert list(elsewhere.iterdir()) == []
