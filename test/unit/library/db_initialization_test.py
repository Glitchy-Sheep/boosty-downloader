import errno
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from sqlite3 import connect
from uuid import UUID, uuid4

import pytest
from sqlalchemy import ScalarResult, text
from sqlalchemy.sql import Executable
from support.library_db import previous_database

from boosty_downloader.infrastructure import media_publication
from boosty_downloader.infrastructure.library import db_initialization
from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library.db_initialization import (
    initialize_database_library,
)
from boosty_downloader.infrastructure.library.db_library_format import (
    DatabaseInitialization,
    DatabaseLibraryPaths,
    database_library_paths,
)
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase


def _pending(paths: DatabaseLibraryPaths) -> UUID:
    library_id = uuid4()
    receipt = DatabaseInitialization(
        storage='sqlite',
        format_version=5,
        library_id=library_id,
        database_location=paths.location_hash,
    )
    paths.initialization.parent.mkdir(parents=True)
    paths.initialization.write_text(receipt.model_dump_json())
    return library_id


def _files(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob('*')
        if path.is_file()
    }


@pytest.mark.parametrize('database_exists', [False, True])
def test_only_owned_missing_or_complete_empty_primary_can_resume(
    tmp_path: Path, *, database_exists: bool
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    library_id = _pending(paths)
    if database_exists:
        LibraryDatabase.create(paths.database, library_id=library_id).close()
    receipt_bytes = paths.initialization.read_bytes()
    assert initialize_database_library(paths) == library_id
    assert paths.initialization.read_bytes() == receipt_bytes
    assert LibraryDatabase.inspect(paths.database).library_id == library_id
    assert json.loads(paths.marker.read_bytes())['library_id'] == str(library_id)


def test_unverified_runtime_cannot_publish_a_receipt_or_create_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    monkeypatch.setattr(sqlite3, 'sqlite_version_info', (3, 50, 4))
    with pytest.raises(LibraryDatabaseError, match='unverified'):
        initialize_database_library(paths)
    assert list(tmp_path.iterdir()) == []


def test_initialization_handle_does_not_configure_wal_or_rotate_backup(tmp_path: Path):
    path = tmp_path.resolve() / 'library.db'
    with LibraryDatabase.create(path) as database:
        library_id = database.identity.library_id
    with closing(connect(path)) as connection:
        connection.execute('PRAGMA journal_mode=DELETE')
    before = _files(tmp_path)
    with (
        LibraryDatabase.open_for_initialization(
            path, expected_library_id=library_id
        ) as database,
        database.transaction() as session,
    ):
        db_initialization._require_empty(session)
    assert _files(tmp_path) == before


def test_initialization_handle_never_migrates_an_old_owned_schema(tmp_path: Path):
    path = previous_database(tmp_path.resolve() / 'library.db')
    library_id = LibraryDatabase.inspect(path).library_id
    before = _files(tmp_path)
    with pytest.raises(LibraryDatabaseError, match='initialization cannot migrate'):
        LibraryDatabase.open_for_initialization(path, expected_library_id=library_id)
    assert _files(tmp_path) == before


@pytest.mark.parametrize(
    'statement',
    [
        'INSERT INTO marks (post_row_id, favorite) VALUES (999, 1)',
        "INSERT INTO media_marks (post_row_id, media_id, position) VALUES (999, 'orphan', 2)",
        "INSERT INTO post_tags (post_row_id, tag) VALUES (999, 'orphan')",
    ],
)
def test_pending_empty_check_includes_orphaned_canonical_records(
    tmp_path: Path, statement: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    library_id = _pending(paths)
    LibraryDatabase.create(paths.database, library_id=library_id).close()
    with closing(connect(paths.database)) as connection:
        connection.execute(statement)
        connection.commit()
    before = _files(tmp_path)
    with pytest.raises(LibraryDatabaseError, match='not empty'):
        initialize_database_library(paths)
    assert _files(tmp_path) == before


def _add_unproven_initialization_state(path: Path, state: str) -> None:
    with closing(connect(path)) as connection:
        match state:
            case 'empty-table':
                connection.execute('CREATE TABLE unrelated(value TEXT)')
            case 'populated-table':
                connection.execute('CREATE TABLE unrelated(value TEXT)')
                connection.execute("INSERT INTO unrelated VALUES ('preserved data')")
            case 'virtual-table':
                connection.execute('CREATE VIRTUAL TABLE unrelated USING fts5(value)')
            case 'logical-search':
                connection.execute(
                    "INSERT INTO posts_fts(rowid, title, body) VALUES (123, 'orphan', 'orphan')"
                )
        connection.commit()
        assert connection.execute('PRAGMA quick_check').fetchone() == ('ok',)


@pytest.mark.parametrize(
    'state', ['empty-table', 'populated-table', 'virtual-table', 'logical-search']
)
def test_pending_database_refuses_unknown_tables_and_orphaned_search_rows(
    tmp_path: Path, state: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    library_id = _pending(paths)
    LibraryDatabase.create(paths.database, library_id=library_id).close()
    _add_unproven_initialization_state(paths.database, state)
    before = _files(tmp_path)
    modified = {path: path.stat().st_mtime_ns for path in paths.root.rglob('*')}
    with pytest.raises(LibraryDatabaseError, match=r'unknown table|not empty'):
        initialize_database_library(paths)
    assert not paths.marker.exists()
    assert _files(tmp_path) == before
    assert {path: path.stat().st_mtime_ns for path in paths.root.rglob('*')} == modified


@pytest.mark.parametrize('unknown_table', [False, True])
def test_schema_validation_closes_its_cursor_before_leaving_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, unknown_table: bool
) -> None:
    results: list[ScalarResult[object]] = []
    with (
        LibraryDatabase.create(tmp_path.resolve() / 'library.db') as database,
        database.transaction() as session,
    ):
        if unknown_table:
            session.execute(text('CREATE TABLE unrelated (value TEXT)'))
        scalars = session.scalars

        def capture_result(statement: Executable) -> ScalarResult[object]:
            result = scalars(statement)
            results.append(result)
            return result

        monkeypatch.setattr(session, 'scalars', capture_result)
        if unknown_table:
            with pytest.raises(LibraryDatabaseError, match='unknown table'):
                db_initialization._require_known_tables(session)
        else:
            db_initialization._require_known_tables(session)
        assert len(results) == 1
        assert results[0].closed


@pytest.mark.parametrize(
    'state', ['populated-table', 'virtual-table', 'logical-search']
)
def test_ready_database_keeps_its_existing_schema_acceptance_policy(
    tmp_path: Path, state: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    library_id = initialize_database_library(paths)
    _add_unproven_initialization_state(paths.database, state)
    before = _files(tmp_path)
    assert initialize_database_library(paths) == library_id
    assert _files(tmp_path) == before


def test_pending_empty_library_allows_fts_shadow_and_sqlite_statistics_rows(
    tmp_path: Path,
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    library_id = _pending(paths)
    LibraryDatabase.create(paths.database, library_id=library_id).close()
    with closing(connect(paths.database)) as connection:
        connection.execute('ANALYZE')
        assert (
            connection.execute('SELECT COUNT(*) FROM posts_fts_config').fetchone()[0]
            > 0
        )
        assert connection.execute('SELECT COUNT(*) FROM sqlite_stat1').fetchone()[0] > 0
    assert initialize_database_library(paths) == library_id


@pytest.mark.parametrize('state', ['populated-table', 'logical-search'])
def test_final_pending_check_observes_noncanonical_state_added_after_preflight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    validate_snapshot = db_initialization._validate_empty_snapshot

    def validate_then_change(paths: DatabaseLibraryPaths, library_id: UUID) -> None:
        validate_snapshot(paths, library_id)
        _add_unproven_initialization_state(paths.database, state)

    monkeypatch.setattr(
        db_initialization, '_validate_empty_snapshot', validate_then_change
    )
    with pytest.raises(LibraryDatabaseError, match=r'unknown table|not empty'):
        initialize_database_library(paths)
    assert not paths.marker.exists()
    with closing(connect(paths.database)) as connection:
        if state == 'populated-table':
            assert connection.execute('SELECT value FROM unrelated').fetchone() == (
                'preserved data',
            )
        else:
            assert connection.execute('SELECT rowid FROM posts_fts').fetchone() == (
                123,
            )


@pytest.mark.parametrize('change', ['schema', 'identity'])
def test_concurrently_published_ready_marker_requires_actual_database_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    open_pending = LibraryDatabase.open_for_initialization
    expected_after_peer: dict[str, bytes] = {}

    def open_then_peer_completes_and_changes_database(
        _cls: type[LibraryDatabase], path: Path, *, expected_library_id: UUID
    ) -> LibraryDatabase:
        database = open_pending(path, expected_library_id=expected_library_id)
        paths.marker.write_text(
            json.dumps(
                {
                    'storage': 'sqlite',
                    'format_version': 5,
                    'library_id': str(expected_library_id),
                }
            )
        )
        with closing(connect(path)) as writer:
            if change == 'schema':
                writer.execute('UPDATE meta SET schema_version=99')
            else:
                writer.execute('UPDATE meta SET library_id=?', (str(uuid4()),))
            writer.commit()
        expected_after_peer.update(_files(tmp_path))
        return database

    monkeypatch.setattr(
        LibraryDatabase,
        'open_for_initialization',
        classmethod(open_then_peer_completes_and_changes_database),
    )
    with pytest.raises(LibraryDatabaseError):
        initialize_database_library(paths)
    assert paths.marker.exists()
    assert _files(tmp_path) == expected_after_peer


@pytest.mark.parametrize(
    'damage',
    ['partial', 'foreign', 'old-schema', 'future-schema', 'nonempty', 'backup'],
)
def test_pending_primary_cannot_be_repaired_adopted_migrated_or_cleared(
    tmp_path: Path, damage: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    library_id = _pending(paths)
    match damage:
        case 'partial':
            paths.database.write_bytes(b'partial database')
        case 'old-schema':
            previous_database(paths.database)
            with closing(connect(paths.database)) as connection:
                connection.execute('UPDATE meta SET library_id=?', (str(library_id),))
                connection.commit()
        case _:
            database_id = uuid4() if damage == 'foreign' else library_id
            LibraryDatabase.create(paths.database, library_id=database_id).close()
            with closing(connect(paths.database)) as connection:
                if damage == 'future-schema':
                    connection.execute('UPDATE meta SET schema_version=99')
                elif damage == 'nonempty':
                    connection.execute("INSERT INTO authors (author) VALUES ('alice')")
                connection.commit()
            if damage == 'backup':
                paths.database.with_name('library.db.bak').write_bytes(
                    b'prior recovery'
                )
    before = _files(tmp_path)
    with pytest.raises(LibraryDatabaseError):
        initialize_database_library(paths)
    assert _files(tmp_path) == before
    assert not paths.marker.exists()


def test_pending_receipt_does_not_allow_changing_cache_location(tmp_path: Path):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    _pending(paths)
    changed = database_library_paths(paths.root, tmp_path.resolve() / 'other-cache')
    before = _files(tmp_path)
    with pytest.raises(LibraryDatabaseError, match='another database location'):
        initialize_database_library(changed)
    assert _files(tmp_path) == before
    assert not changed.database.parent.exists()


@pytest.mark.parametrize('suffix', ['-wal', '-shm', '-journal', '.bak'])
def test_pending_missing_database_preserves_recovery_auxiliaries(
    tmp_path: Path, suffix: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    _pending(paths)
    paths.database.with_name(paths.database.name + suffix).write_bytes(b'preserved')
    before = _files(tmp_path)
    with pytest.raises(LibraryDatabaseError):
        initialize_database_library(paths)
    assert _files(tmp_path) == before
    assert not paths.database.exists()


def test_final_empty_check_observes_rows_added_after_private_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    validate_snapshot = db_initialization._validate_empty_snapshot

    def validate_then_insert(paths: DatabaseLibraryPaths, library_id: UUID) -> None:
        validate_snapshot(paths, library_id)
        with closing(connect(paths.database)) as writer:
            writer.execute("INSERT INTO authors (author) VALUES ('concurrent-author')")
            writer.commit()

    monkeypatch.setattr(
        db_initialization, '_validate_empty_snapshot', validate_then_insert
    )
    with pytest.raises(LibraryDatabaseError, match='not empty'):
        initialize_database_library(paths)
    assert not paths.marker.exists()
    with closing(connect(paths.database)) as connection:
        assert connection.execute('SELECT author FROM authors').fetchone() == (
            'concurrent-author',
        )


def test_independently_published_ready_marker_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    publish = db_initialization.publish_marker
    foreign_marker = json.dumps(
        {'storage': 'sqlite', 'format_version': 5, 'library_id': str(uuid4())}
    ).encode()

    def publish_after_foreign_ready(path: Path, data: bytes) -> None:
        if path == paths.marker:
            publish(path, foreign_marker)
        publish(path, data)

    monkeypatch.setattr(
        db_initialization, 'publish_marker', publish_after_foreign_ready
    )
    with pytest.raises(LibraryDatabaseError, match='different library'):
        initialize_database_library(paths)
    assert paths.marker.read_bytes() == foreign_marker
    assert not paths.database.with_name('library.db.bak').exists()


def _unsupported_rename(_source: Path, _destination: Path) -> None:
    raise OSError(errno.ENOSYS, 'Exclusive rename unavailable')


def test_hardlink_publication_fallback_leaves_unshared_complete_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    monkeypatch.setattr(media_publication, '_rename_exclusively', _unsupported_rename)
    initialize_database_library(paths)
    assert paths.marker.stat().st_nlink == 1
    assert paths.initialization.stat().st_nlink == 1
    assert not list(paths.marker.parent.glob('*.tmp'))


def test_unsupported_publication_does_not_create_a_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    monkeypatch.setattr(media_publication, '_rename_exclusively', _unsupported_rename)

    def refuse_link(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.ENOTSUP, 'Hardlinks unavailable')

    monkeypatch.setattr(media_publication.os, 'link', refuse_link)
    with pytest.raises(OSError, match='Hardlinks unavailable'):
        initialize_database_library(paths)
    assert _files(tmp_path) == {}
    assert not paths.database.exists()
