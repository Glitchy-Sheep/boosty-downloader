import json
import sqlite3
import sqlite3.dbapi2
import subprocess
import sys
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from urllib.parse import unquote
from uuid import uuid4

import pytest
from support.library_db import NOW, previous_database

from boosty_downloader.cli.database_library import (
    prepare_database_download,
    prepare_database_preview,
)
from boosty_downloader.domain.stored_post import PostMetadata, PostSync, StoredPost
from boosty_downloader.infrastructure.library import _db_snapshot
from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library.db_library_format import (
    DatabaseInitialization,
    DatabaseLibraryPaths,
    database_library_paths,
)

_HOT_JOURNAL_SCRIPT = """
import sqlite3
import sys
import time
from pathlib import Path
connection = sqlite3.connect(sys.argv[1])
connection.execute('PRAGMA synchronous=FULL')
connection.execute('PRAGMA cache_size=8')
connection.execute('BEGIN IMMEDIATE')
connection.execute("UPDATE posts SET title='Uncommitted'")
connection.execute('UPDATE rollback_spill SET payload=zeroblob(16384)')
Path(sys.argv[2]).write_text('ready')
while True:
    time.sleep(1)
"""


@dataclass(frozen=True, slots=True)
class _FileState:
    data: bytes | None
    modified_ns: int


def _state(*roots: Path) -> dict[Path, _FileState]:
    result: dict[Path, _FileState] = {}
    for root in roots:
        if not root.exists():
            continue
        for path in [root, *root.rglob('*')]:
            result[path] = _FileState(
                path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns
            )
    return result


def _seed(paths: DatabaseLibraryPaths) -> str:
    post = PostMetadata(
        '12345678-full', 'alice', 'https://boosty.to/alice', 'Original', NOW, NOW
    )
    with prepare_database_download(paths) as store:
        folder = store.choose_post_folder(post)
        store.save_post(folder, StoredPost(post, PostSync(NOW, NOW), [], {}))
    return folder


def _private_snapshots(
    monkeypatch: pytest.MonkeyPatch, temporary_root: Path
) -> list[Path]:
    temporary_root.mkdir()
    created: list[Path] = []

    def temporary_directory(*, prefix: str) -> TemporaryDirectory[str]:
        directory = TemporaryDirectory(prefix=prefix, dir=temporary_root)
        created.append(Path(directory.name).resolve())
        return directory

    connect = sqlite3.dbapi2.connect

    def private_connect(
        database: str, *args: object, **kwargs: object
    ) -> sqlite3.Connection:
        if database != ':memory:':
            filename = unquote(database.removeprefix('file:').split('?', 1)[0])
            assert Path(filename).is_relative_to(temporary_root)
        return connect(database, *args, **kwargs)

    monkeypatch.setattr(_db_snapshot, 'TemporaryDirectory', temporary_directory)
    monkeypatch.setattr(sqlite3, 'connect', private_connect)
    monkeypatch.setattr(sqlite3.dbapi2, 'connect', private_connect)
    return created


def _update_title(connection: sqlite3.Connection, title: str) -> None:
    metadata = json.loads(
        connection.execute('SELECT saved_metadata FROM posts').fetchone()[0]
    )
    metadata['title'] = title
    connection.execute(
        'UPDATE posts SET title=?, saved_metadata=?', (title, json.dumps(metadata))
    )
    connection.commit()


def test_empty_preview_never_probes_sqlite_or_creates_user_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(
        tmp_path.resolve() / 'library', tmp_path.resolve() / 'cache'
    )
    config = tmp_path / 'config.yaml'
    log = tmp_path / 'debug.log'
    config.write_text('existing configuration')
    log.write_text('existing log')
    before = _state(paths.root, paths.database.parent, config, log)

    def forbid_sqlite(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        message = 'Empty preview must not open SQLite'
        raise AssertionError(message)

    monkeypatch.setattr(sqlite3, 'sqlite_version_info', (3, 50, 4))
    monkeypatch.setattr(sqlite3, 'connect', forbid_sqlite)
    monkeypatch.setattr(sqlite3.dbapi2, 'connect', forbid_sqlite)
    with prepare_database_preview(paths) as locator:
        assert locator.find_post('alice', '12345678-full') is None
        post = PostMetadata(
            '12345678-full', 'alice', 'https://boosty.to/alice', 'Title', NOW, NOW
        )
        assert locator.choose_post_folder(post) == 'alice/2026-10-01 - Title (12345678)'
    assert _state(paths.root, paths.database.parent, config, log) == before


@pytest.mark.parametrize('fail_inside', [False, True])
def test_clean_preview_only_opens_one_private_snapshot_and_cleans_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, fail_inside: bool
):
    paths = database_library_paths(
        tmp_path.resolve() / 'library', tmp_path.resolve() / 'cache'
    )
    folder = _seed(paths)
    assert not paths.database.with_name('library.db-wal').exists()
    assert not paths.database.with_name('library.db-shm').exists()
    config = tmp_path / 'config.yaml'
    log = tmp_path / 'debug.log'
    config.write_text('existing configuration')
    log.write_text('existing log')
    before = _state(paths.root, paths.database.parent, config, log)
    snapshots = _private_snapshots(monkeypatch, tmp_path.resolve() / 'private')

    def preview() -> None:
        with prepare_database_preview(paths) as locator:
            found = locator.find_post('alice', '12345678-full')
            assert found is not None
            assert found.record is not None
            assert found.folder == folder
            assert found.record.post.title == 'Original'
            assert len(snapshots) == 1
            assert snapshots[0].exists()
            assert _state(paths.root, paths.database.parent, config, log) == before
            if fail_inside:
                message = 'caller failed'
                raise RuntimeError(message)

    if fail_inside:
        with pytest.raises(RuntimeError, match='caller failed'):
            preview()
    else:
        preview()
    assert len(snapshots) == 1
    assert not snapshots[0].exists()
    assert _state(paths.root, paths.database.parent, config, log) == before


def test_preview_reads_committed_wal_and_retains_that_generation_during_writer_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    _seed(paths)
    with closing(sqlite3.connect(paths.database)) as writer:
        writer.execute('PRAGMA wal_autocheckpoint=0')
        _update_title(writer, 'Committed WAL')
        assert paths.database.with_name('library.db-wal').stat().st_size > 0
        snapshots = _private_snapshots(monkeypatch, tmp_path.resolve() / 'private')
        before = _state(paths.root)
        with prepare_database_preview(paths) as locator:
            found = locator.find_post('alice', '12345678-full')
            assert found is not None
            assert found.record is not None
            assert found.record.post.title == 'Committed WAL'
            assert _state(paths.root) == before
            _update_title(writer, 'Later commit')
            after_writer = _state(paths.root)
            found_again = locator.find_post('alice', '12345678-full')
            assert found_again is not None
            assert found_again.record is not None
            assert found_again.record.post.title == 'Committed WAL'
            assert _state(paths.root) == after_writer
        assert _state(paths.root) == after_writer
        assert not snapshots[0].exists()


def test_preview_rejects_pending_initialization_without_completing_it(tmp_path: Path):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    receipt = DatabaseInitialization(
        storage='sqlite',
        format_version=5,
        library_id=uuid4(),
        database_location=paths.location_hash,
    )
    paths.initialization.parent.mkdir(parents=True)
    paths.initialization.write_text(receipt.model_dump_json())
    before = _state(paths.root)
    with (
        pytest.raises(LibraryDatabaseError, match='unfinished'),
        prepare_database_preview(paths),
    ):
        pytest.fail('A pending library cannot enter preview')
    assert _state(paths.root) == before


def test_ready_preview_rejects_unverified_runtime_before_making_a_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    _seed(paths)
    before = _state(paths.root)
    snapshots = _private_snapshots(monkeypatch, tmp_path.resolve() / 'private')
    monkeypatch.setattr(sqlite3, 'sqlite_version_info', (3, 50, 4))
    with (
        pytest.raises(LibraryDatabaseError, match='unverified'),
        prepare_database_preview(paths),
    ):
        pytest.fail('An unverified runtime cannot enter primary database preview')
    assert snapshots == []
    assert _state(paths.root) == before


@pytest.mark.parametrize('damage', ['old', 'future', 'foreign', 'corrupt', 'missing'])
def test_invalid_ready_primary_is_preserved_and_never_yielded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, damage: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    _seed(paths)
    if damage == 'old':
        replacement = previous_database(tmp_path / 'old.db')
        library_id = json.loads(paths.marker.read_bytes())['library_id']
        with closing(sqlite3.connect(replacement)) as connection:
            connection.execute('UPDATE meta SET library_id=?', (library_id,))
            connection.commit()
        replacement.replace(paths.database)
    elif damage in {'future', 'foreign'}:
        with closing(sqlite3.connect(paths.database)) as connection:
            if damage == 'future':
                connection.execute('UPDATE meta SET schema_version=99')
            else:
                connection.execute('UPDATE meta SET library_id=?', (str(uuid4()),))
            connection.commit()
    elif damage == 'corrupt':
        paths.database.write_bytes(b'preserve corrupt primary')
    else:
        paths.database.unlink()
    before = _state(paths.root)
    snapshots = _private_snapshots(monkeypatch, tmp_path.resolve() / 'private')
    with (
        pytest.raises(LibraryDatabaseError) as failure,
        prepare_database_preview(paths),
    ):
        pytest.fail('Invalid storage cannot enter preview')
    assert str(paths.database) in str(failure.value)
    assert str(paths.database.with_name('library.db.bak')) in str(failure.value)
    assert _state(paths.root) == before
    assert all(not snapshot.exists() for snapshot in snapshots)


def test_preview_refuses_unstable_source_after_bounded_attempts_and_cleans_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    _seed(paths)
    original_bytes = paths.database.read_bytes()
    snapshots = _private_snapshots(monkeypatch, tmp_path.resolve() / 'private')
    copied_primary = 0

    def copy_then_replace(source: Path, destination: Path) -> None:
        nonlocal copied_primary
        copyfile(source, destination)
        if source == paths.database:
            copied_primary += 1
            replacement = source.with_name('replacement.db')
            copyfile(source, replacement)
            replacement.replace(source)

    monkeypatch.setattr(_db_snapshot, 'copyfile', copy_then_replace)
    with (
        pytest.raises(LibraryDatabaseError, match='stable snapshot'),
        prepare_database_preview(paths),
    ):
        pytest.fail('Unstable source cannot enter preview')
    assert copied_primary == 3
    assert paths.database.read_bytes() == original_bytes
    assert len(snapshots) == 3
    assert all(not snapshot.exists() for snapshot in snapshots)


def _leave_hot_journal(database: Path, barrier: Path) -> None:
    with subprocess.Popen(  # noqa: S603 - trusted script and pytest-owned paths
        [sys.executable, '-c', _HOT_JOURNAL_SCRIPT, str(database), str(barrier)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        deadline = time.monotonic() + 10
        try:
            while not barrier.exists():
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=2)
                    pytest.fail(
                        f'Writer failed before journal spill: {stdout}\n{stderr}'
                    )
                if time.monotonic() >= deadline:
                    pytest.fail('Writer did not reach journal spill')
                time.sleep(0.01)
        finally:
            process.kill()
            process.communicate(timeout=5)


def test_hot_rollback_journal_is_preserved_when_private_read_requires_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    _seed(paths)
    with closing(sqlite3.connect(paths.database)) as connection:
        connection.execute('PRAGMA journal_mode=DELETE')
        connection.execute('CREATE TABLE rollback_spill(payload BLOB)')
        connection.executemany(
            'INSERT INTO rollback_spill VALUES (?)', [(b'committed' * 2048,)] * 64
        )
        connection.commit()
    _leave_hot_journal(paths.database, tmp_path / 'writer-ready')
    journal = paths.database.with_name('library.db-journal')
    assert journal.stat().st_size > 512
    assert journal.read_bytes()[:8] != b'\0' * 8
    before = _state(paths.root)
    with monkeypatch.context() as local:
        snapshots = _private_snapshots(local, tmp_path.resolve() / 'private')
        with (
            pytest.raises(LibraryDatabaseError) as failure,
            prepare_database_preview(paths),
        ):
            pytest.fail('A read-only preview cannot ignore required journal recovery')
        assert str(paths.database) in str(failure.value)
        assert str(paths.database.with_name('library.db.bak')) in str(failure.value)
        assert _state(paths.root) == before
        assert len(snapshots) == 1
        assert not snapshots[0].exists()
    with closing(sqlite3.connect(paths.database)) as recovery:
        assert recovery.execute('SELECT title FROM posts').fetchone() == ('Original',)
