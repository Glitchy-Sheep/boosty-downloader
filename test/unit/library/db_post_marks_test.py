"""Primary viewing marks reject corrupt rows and preserve atomic independent snapshots."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from shutil import rmtree
from threading import Barrier, Event
from traceback import format_exception
from typing import TYPE_CHECKING, TypeAlias
from unittest.mock import Mock

import pytest
from sqlalchemy import event, select, text

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.stored_post import (
    LockedPost,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library._db_models import (
    DbMarks,
    DbMediaMarks,
    DbPost,
)
from boosty_downloader.infrastructure.library.db_post_marks import DatabasePostMarks
from boosty_downloader.infrastructure.library.db_post_store import DatabasePostStore
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase
from boosty_downloader.infrastructure.library.errors import (
    InvalidPostRecordError,
    InvalidViewerRecordError,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from sqlalchemy import Connection

NOW = datetime(2026, 11, 15, 12, 34, 56, 123456, tzinfo=timezone.utc)
POST_ID = 'abcdefgh-first'
FOLDER = 'writer/2026-11-15 - Lesson (abcdefgh)'
MEDIA_ID = 'audio:retained'
THREAD_TIMEOUT = 10
DatabaseRows: TypeAlias = dict[str, list[dict[str, object]]]


class Operation(Enum):
    read = 'read'
    save = 'save'


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'library'


@pytest.fixture
def database(tmp_path: Path) -> Generator[LibraryDatabase, None, None]:
    with LibraryDatabase.create(tmp_path / 'library.db') as database:
        yield database


@pytest.fixture
def records(root: Path, database: LibraryDatabase) -> DatabasePostStore:
    return DatabasePostStore(root, database)


@pytest.fixture
def store(root: Path, database: LibraryDatabase) -> DatabasePostMarks:
    return DatabasePostMarks(root, database)


@pytest.fixture
def record(records: DatabasePostStore) -> StoredPost:
    record = StoredPost(
        PostMetadata(
            POST_ID, 'writer', 'https://boosty.to/example', 'Lesson', NOW, NOW
        ),
        PostSync(NOW, NOW),
    )
    records.save_post(FOLDER, record)
    return record


@pytest.fixture
def marks(record: StoredPost, store: DatabasePostMarks) -> PostMarks:
    marks = PostMarks(
        seen_at=NOW,
        favorite=True,
        positions={
            MEDIA_ID: PlaybackPosition(42.125, NOW),
            'future:unknown': PlaybackPosition(10),
        },
    )
    store.save_marks(record.post.author, record.post.id, marks)
    return marks


def _post_row_id(database: LibraryDatabase) -> int:
    with database.transaction() as session:
        return session.scalars(select(DbPost.id)).one()


def _rows(database: LibraryDatabase) -> DatabaseRows:
    queries = {
        'authors': 'SELECT * FROM authors ORDER BY author',
        'posts': 'SELECT * FROM posts ORDER BY id',
        'media': 'SELECT * FROM media ORDER BY post_row_id, media_id',
        'tags': 'SELECT * FROM post_tags ORDER BY post_row_id, tag',
        'fts': 'SELECT rowid, * FROM posts_fts ORDER BY rowid',
        'marks': 'SELECT * FROM marks ORDER BY post_row_id',
        'playback': 'SELECT * FROM media_marks ORDER BY post_row_id, media_id',
    }
    with database.engine.connect() as connection:
        return {
            name: [dict(row) for row in connection.execute(text(query)).mappings()]
            for name, query in queries.items()
        }


def _run(operation: Operation, store: DatabasePostMarks) -> PostMarks | None:
    match operation:
        case Operation.read:
            return store.get_marks('writer', POST_ID)
        case Operation.save:
            store.save_marks('writer', POST_ID, PostMarks())
            return None


def test_positions_without_scalar_marks_remain_independent(
    database: LibraryDatabase,
    record: StoredPost,
    store: DatabasePostMarks,
):
    post_row_id = _post_row_id(database)
    with database.transaction() as session:
        session.add(
            DbMediaMarks(
                post_row_id=post_row_id,
                media_id=MEDIA_ID,
                position=19.5,
                finished_at=NOW,
            )
        )
    assert store.get_marks(record.post.author, record.post.id) == PostMarks(
        positions={MEDIA_ID: PlaybackPosition(19.5, NOW)}
    )
    before = _rows(database)
    assert before['marks'] == []
    store.save_marks('writer', POST_ID, PostMarks(favorite=True))
    assert store.get_marks('writer', POST_ID) == PostMarks(favorite=True)
    assert _rows(database)['playback'] == []


@pytest.mark.parametrize('operation', list(Operation))
@pytest.mark.parametrize('favorite', [2, 'not-a-boolean', 0.5, b'\x01'])
def test_raw_favorite_corruption_is_not_coerced_or_overwritten(
    database: LibraryDatabase,
    marks: PostMarks,
    store: DatabasePostMarks,
    operation: Operation,
    favorite: object,
):
    assert marks.favorite
    with database.engine.begin() as connection:
        connection.execute(
            text('UPDATE marks SET favorite = :value'), {'value': favorite}
        )
    before = _rows(database)
    with pytest.raises(InvalidViewerRecordError, match='favorite'):
        _run(operation, store)
    assert _rows(database) == before


@pytest.mark.parametrize('operation', list(Operation))
@pytest.mark.parametrize('value', [-1, float('inf'), 'private-invalid-seconds'])
def test_bad_persisted_seconds_are_errors_before_replacement(
    database: LibraryDatabase,
    marks: PostMarks,
    store: DatabasePostMarks,
    operation: Operation,
    value: object,
):
    assert marks.positions
    with database.engine.begin() as connection:
        connection.exec_driver_sql('PRAGMA ignore_check_constraints=ON')
        connection.execute(
            text('UPDATE media_marks SET position = :value'), {'value': value}
        )
        connection.exec_driver_sql('PRAGMA ignore_check_constraints=OFF')
    before = _rows(database)
    with pytest.raises(InvalidViewerRecordError) as raised:
        _run(operation, store)
    assert 'private-invalid-seconds' not in ''.join(format_exception(raised.value))
    assert _rows(database) == before


@pytest.mark.parametrize('operation', list(Operation))
@pytest.mark.parametrize('field', ['seen', 'finished'])
@pytest.mark.parametrize('value', ['private-invalid-time', '2026-11-15', 123])
@pytest.mark.usefixtures('marks')
def test_bad_persisted_timestamps_remain_sanitized_errors(
    database: LibraryDatabase,
    store: DatabasePostMarks,
    operation: Operation,
    field: str,
    value: object,
):
    statement = (
        'UPDATE marks SET seen_at = :value'
        if field == 'seen'
        else 'UPDATE media_marks SET finished_at = :value'
    )
    with database.engine.begin() as connection:
        connection.execute(text(statement), {'value': value})
    before = _rows(database)
    with pytest.raises(InvalidViewerRecordError, match='timestamp') as raised:
        _run(operation, store)
    assert 'private-invalid-time' not in ''.join(format_exception(raised.value))
    assert _rows(database) == before


@pytest.mark.parametrize('operation', list(Operation))
@pytest.mark.parametrize('media_id', ['', '  '])
def test_blank_stored_media_identity_is_not_silently_discarded(
    database: LibraryDatabase,
    record: StoredPost,
    store: DatabasePostMarks,
    operation: Operation,
    media_id: str,
):
    assert record.post.id == POST_ID
    post_row_id = _post_row_id(database)
    with database.transaction() as session:
        session.add(
            DbMediaMarks(post_row_id=post_row_id, media_id=media_id, position=0)
        )
    before = _rows(database)
    with pytest.raises(InvalidViewerRecordError):
        _run(operation, store)
    assert _rows(database) == before


@pytest.mark.parametrize('operation', list(Operation))
@pytest.mark.parametrize('scalar', [False, True])
def test_never_saved_locked_post_cannot_hide_unexpected_user_marks(
    database: LibraryDatabase,
    records: DatabasePostStore,
    store: DatabasePostMarks,
    operation: Operation,
    *,
    scalar: bool,
):
    metadata = PostMetadata(
        POST_ID, 'writer', 'https://boosty.to/example', 'Locked', NOW, NOW
    )
    records.save_locked_post(LockedPost(metadata, NOW))
    post_row_id = _post_row_id(database)
    with database.transaction() as session:
        if scalar:
            session.add(DbMarks(post_row_id=post_row_id, favorite=False))
        else:
            session.add(
                DbMediaMarks(
                    post_row_id=post_row_id, media_id='future:unknown', position=0
                )
            )
    before = _rows(database)
    with pytest.raises(InvalidViewerRecordError, match='without a saved generation'):
        _run(operation, store)
    assert _rows(database) == before


@pytest.mark.parametrize('operation', list(Operation))
def test_corrupt_saved_identity_never_authorizes_user_marks(
    database: LibraryDatabase,
    record: StoredPost,
    store: DatabasePostMarks,
    operation: Operation,
):
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        row.saved_metadata = replace(record.post, id='abcdefgh-foreign')
    before = _rows(database)
    with pytest.raises(InvalidPostRecordError, match='identity disagrees'):
        _run(operation, store)
    assert _rows(database) == before


def test_marks_write_leaves_post_metadata_fts_and_files_unchanged(
    root: Path,
    database: LibraryDatabase,
    record: StoredPost,
    store: DatabasePostMarks,
):
    assert record.post.id == POST_ID
    retained = root / FOLDER / 'notes.txt'
    retained.write_bytes(b'user file')
    modified = retained.stat().st_mtime_ns
    before = _rows(database)
    store.save_marks(
        'writer',
        POST_ID,
        PostMarks(
            seen_at=NOW, favorite=True, positions={MEDIA_ID: PlaybackPosition(50, NOW)}
        ),
    )
    after = _rows(database)
    for table in ('authors', 'posts', 'media', 'tags', 'fts'):
        assert after[table] == before[table]
    assert retained.read_bytes() == b'user file'
    assert retained.stat().st_mtime_ns == modified
    assert list((root / FOLDER).iterdir()) == [retained]


def test_failure_after_scalar_change_and_position_delete_rolls_back_complete_snapshot(
    root: Path,
    database: LibraryDatabase,
    store: DatabasePostMarks,
    marks: PostMarks,
):
    before = _rows(database)
    observed: list[bool] = []

    def fail_after_delete(
        connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if not statement.startswith('DELETE FROM media_marks'):
            return
        assert connection.execute(text('SELECT favorite FROM marks')).scalar_one() == 0
        assert (
            connection.execute(text('SELECT COUNT(*) FROM media_marks')).scalar_one()
            == 0
        )
        observed.append(True)
        message = 'Interrupted complete mark replacement'
        raise OSError(message)

    event.listen(database.engine, 'after_cursor_execute', fail_after_delete)
    try:
        with pytest.raises(OSError, match='Interrupted complete mark replacement'):
            store.save_marks(
                'writer',
                POST_ID,
                PostMarks(positions={'future:new': PlaybackPosition(99)}),
            )
    finally:
        event.remove(database.engine, 'after_cursor_execute', fail_after_delete)
    assert observed == [True]
    assert _rows(database) == before
    assert store.get_marks('writer', POST_ID) == marks
    with LibraryDatabase.open(database.path) as reopened:
        assert DatabasePostMarks(root, reopened).get_marks('writer', POST_ID) == marks


def test_invalid_snapshot_is_rejected_before_opening_a_write_transaction(
    database: LibraryDatabase,
    store: DatabasePostMarks,
    marks: PostMarks,
    monkeypatch: pytest.MonkeyPatch,
):
    before = _rows(database)
    invalid = deepcopy(marks)
    invalid.positions[MEDIA_ID].seconds = -1
    writer = Mock(side_effect=AssertionError('Writer opened'))
    monkeypatch.setattr(database, 'transaction', writer)
    with pytest.raises(InvalidViewerRecordError):
        store.save_marks('writer', POST_ID, invalid)
    writer.assert_not_called()
    assert _rows(database) == before


@pytest.mark.parametrize(
    'timestamp',
    [
        '2026-11-15 12:34:56.123456',
        '2026-11-15T12:34:56.123456Z',
        '2026-11-15T15:34:56.123456+03:00',
    ],
)
def test_persisted_timestamp_forms_normalize_to_the_same_utc_instant(
    database: LibraryDatabase,
    store: DatabasePostMarks,
    marks: PostMarks,
    timestamp: str,
):
    with database.engine.begin() as connection:
        connection.execute(
            text('UPDATE marks SET seen_at = :value'), {'value': timestamp}
        )
        connection.execute(
            text('UPDATE media_marks SET finished_at = :value WHERE media_id = :media'),
            {'value': timestamp, 'media': MEDIA_ID},
        )
    restored = store.get_marks('writer', POST_ID)
    assert restored == marks
    assert restored is not None
    assert restored.seen_at is not None
    assert restored.seen_at.tzinfo is timezone.utc


def test_reader_sees_complete_committed_marks_during_uncommitted_replacement(
    database: LibraryDatabase,
    store: DatabasePostMarks,
    marks: PostMarks,
):
    paused, release = Event(), Event()
    updated = PostMarks(positions={'future:new': PlaybackPosition(99)})

    def pause_after_delete(
        _connection: Connection,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if statement.startswith('DELETE FROM media_marks'):
            paused.set()
            assert release.wait(THREAD_TIMEOUT)

    event.listen(database.engine, 'after_cursor_execute', pause_after_delete)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            writer = executor.submit(store.save_marks, 'writer', POST_ID, updated)
            try:
                assert paused.wait(THREAD_TIMEOUT)
                assert store.get_marks('writer', POST_ID) == marks
            finally:
                release.set()
            writer.result(timeout=THREAD_TIMEOUT)
    finally:
        event.remove(database.engine, 'after_cursor_execute', pause_after_delete)
    assert store.get_marks('writer', POST_ID) == updated


def test_concurrent_full_replacements_never_merge_unrelated_snapshots(
    record: StoredPost,
    store: DatabasePostMarks,
):
    assert record.post.id == POST_ID
    barrier = Barrier(2)
    first = PostMarks(
        seen_at=NOW, favorite=True, positions={'future:first': PlaybackPosition(10)}
    )
    second = PostMarks(positions={'future:second': PlaybackPosition(20, NOW)})

    def save(snapshot: PostMarks) -> None:
        barrier.wait(timeout=THREAD_TIMEOUT)
        store.save_marks('writer', POST_ID, snapshot)

    with ThreadPoolExecutor(max_workers=2) as executor:
        writers = [executor.submit(save, snapshot) for snapshot in (first, second)]
        for writer in writers:
            writer.result(timeout=THREAD_TIMEOUT)
    assert store.get_marks('writer', POST_ID) in (first, second)


def test_downloader_update_and_mark_replacement_preserve_both_domains(
    record: StoredPost,
    records: DatabasePostStore,
    store: DatabasePostMarks,
):
    updated = deepcopy(record)
    updated.post.title = 'Downloader update'
    updated.post.tags = ['new']
    updated.sync.synced_at = NOW + timedelta(days=1)
    marks = PostMarks(
        seen_at=NOW, favorite=True, positions={'future:retained': PlaybackPosition(40)}
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        downloader = executor.submit(records.save_post, FOLDER, updated)
        viewer = executor.submit(store.save_marks, 'writer', POST_ID, marks)
        downloader.result(timeout=THREAD_TIMEOUT)
        viewer.result(timeout=THREAD_TIMEOUT)
    located = records.find_post('writer', POST_ID)
    assert located is not None
    assert located.record == updated
    assert store.get_marks('writer', POST_ID) == marks


@pytest.mark.parametrize('locked', [False, True])
@pytest.mark.usefixtures('marks')
def test_only_a_later_post_save_resets_hidden_generation_marks(
    root: Path,
    database: LibraryDatabase,
    records: DatabasePostStore,
    store: DatabasePostMarks,
    *,
    locked: bool,
):
    located = records.find_post('writer', POST_ID)
    assert located is not None
    assert located.record is not None
    record = located.record
    if locked:
        records.save_locked_post(LockedPost(record.post, NOW))
    rmtree(root / FOLDER)
    before = _rows(database)
    assert store.get_marks('writer', POST_ID) == (PostMarks() if locked else None)
    with pytest.raises(LookupError):
        store.save_marks('writer', POST_ID, PostMarks(favorite=True))
    assert _rows(database) == before
    assert not (root / FOLDER).exists()
    records.save_post(FOLDER, record)
    assert store.get_marks('writer', POST_ID) == PostMarks()


def test_marks_remain_portable_after_library_relocation(tmp_path: Path):
    root = tmp_path / 'source'
    record = StoredPost(
        PostMetadata(POST_ID, 'writer', '', 'Lesson', NOW, NOW), PostSync(NOW, NOW)
    )
    expected = PostMarks(
        seen_at=NOW, favorite=True, positions={MEDIA_ID: PlaybackPosition(99, NOW)}
    )
    with LibraryDatabase.create(root / 'library.db') as database:
        DatabasePostStore(root, database).save_post(FOLDER, record)
        DatabasePostMarks(root, database).save_marks('writer', POST_ID, expected)
    moved = tmp_path / 'moved'
    root.rename(moved)
    with LibraryDatabase.open(moved / 'library.db') as database:
        assert (
            DatabasePostMarks(moved, database).get_marks('writer', POST_ID) == expected
        )


@pytest.mark.parametrize('locked', [False, True])
@pytest.mark.usefixtures('marks')
def test_missing_generation_hides_malformed_marks_until_post_save_resets_it(
    root: Path,
    database: LibraryDatabase,
    records: DatabasePostStore,
    store: DatabasePostMarks,
    *,
    locked: bool,
):
    located = records.find_post('writer', POST_ID)
    assert located is not None
    assert located.record is not None
    record = located.record
    if locked:
        records.save_locked_post(LockedPost(record.post, NOW))
    with database.engine.begin() as connection:
        connection.execute(text('UPDATE marks SET favorite = 2'))
        connection.execute(
            text("UPDATE media_marks SET position = 'private-invalid-position'")
        )
    rmtree(root / FOLDER)
    before = _rows(database)
    assert store.get_marks('writer', POST_ID) == (PostMarks() if locked else None)
    with pytest.raises(LookupError):
        store.save_marks('writer', POST_ID, PostMarks())
    assert _rows(database) == before
    assert not (root / FOLDER).exists()
    records.save_post(FOLDER, record)
    assert store.get_marks('writer', POST_ID) == PostMarks()
    assert _rows(database)['marks'] == []
    assert _rows(database)['playback'] == []
