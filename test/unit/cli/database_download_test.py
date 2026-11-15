import json
from contextlib import closing
from pathlib import Path
from sqlite3 import connect
from uuid import uuid4

import pytest
from support.library_db import NOW, previous_database

from boosty_downloader.cli.database_library import prepare_database_download
from boosty_downloader.domain.stored_post import PostMetadata, PostSync, StoredPost
from boosty_downloader.infrastructure.library import _db_backup, db_store
from boosty_downloader.infrastructure.library._db_engine import DatabaseFileIdentity
from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library._db_schema import SchemaIdentity
from boosty_downloader.infrastructure.library.db_initialization import (
    initialize_database_library,
)
from boosty_downloader.infrastructure.library.db_library_format import (
    database_library_paths,
)


def test_download_context_backs_up_once_before_exposing_writable_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    backups: list[SchemaIdentity] = []
    make_backup = db_store.make_library_backup

    def track_backup(
        path: Path, identity: SchemaIdentity, *, source_file: DatabaseFileIdentity
    ) -> None:
        backups.append(identity)
        make_backup(path, identity, source_file=source_file)

    monkeypatch.setattr(db_store, 'make_library_backup', track_backup)
    with prepare_database_download(paths) as store:
        assert len(backups) == 1
        assert paths.marker.exists()
        post = PostMetadata(
            '12345678-full', 'alice', 'https://boosty.to/alice', 'First', NOW, NOW
        )
        store.save_post(
            store.choose_post_folder(post), StoredPost(post, PostSync(NOW, NOW), [], {})
        )
        with closing(connect(paths.database.with_name('library.db.bak'))) as backup:
            assert backup.execute('SELECT COUNT(*) FROM posts').fetchone() == (0,)
    assert len(backups) == 1
    assert not list(paths.root.rglob('post.json'))
    assert not list(paths.root.rglob('author.json'))


def test_backup_failure_prevents_context_body_and_preserves_prior_backup_and_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    initialize_database_library(paths)
    with closing(connect(paths.database)) as connection:
        connection.execute('PRAGMA journal_mode=DELETE')
    backup = paths.database.with_name('library.db.bak')
    backup.write_bytes(b'previous recovery point')
    before = {
        path: path.read_bytes() for path in paths.root.rglob('*') if path.is_file()
    }
    modified = {
        path: path.stat().st_mtime_ns
        for path in paths.root.rglob('*')
        if path.is_file()
    }
    entered = False

    def fail_backup(
        _source: Path,
        destination: Path,
        _identity: SchemaIdentity,
        *,
        source_file: DatabaseFileIdentity,
    ) -> None:
        assert source_file.inode > 0
        destination.write_bytes(b'incomplete backup')
        message = 'injected disk failure'
        raise OSError(message)

    monkeypatch.setattr(_db_backup, '_copy_database', fail_backup)
    with (
        pytest.raises(OSError, match='injected disk failure'),
        prepare_database_download(paths),
    ):
        entered = True
    assert not entered
    assert {
        path: path.read_bytes() for path in paths.root.rglob('*') if path.is_file()
    } == before
    assert {
        path: path.stat().st_mtime_ns
        for path in paths.root.rglob('*')
        if path.is_file()
    } == modified
    assert paths.database.read_bytes()[18:20] == b'\x01\x01'


def test_download_migration_keeps_one_pre_upgrade_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    initialize_database_library(paths)
    library_id = json.loads(paths.marker.read_bytes())['library_id']
    previous = previous_database(tmp_path / 'previous.db')
    with closing(connect(previous)) as connection:
        connection.execute('UPDATE meta SET library_id=?', (library_id,))
        connection.commit()
    previous.replace(paths.database)
    versions: list[int] = []
    make_backup = db_store.make_library_backup

    def track_backup(
        path: Path, identity: SchemaIdentity, *, source_file: DatabaseFileIdentity
    ) -> None:
        versions.append(identity.version)
        make_backup(path, identity, source_file=source_file)

    monkeypatch.setattr(db_store, 'make_library_backup', track_backup)
    with prepare_database_download(paths):
        assert versions == [1]
        with closing(connect(paths.database.with_name('library.db.bak'))) as backup:
            assert backup.execute('SELECT schema_version FROM meta').fetchone() == (1,)
            assert backup.execute('SELECT COUNT(*) FROM posts').fetchone() == (3,)
    assert versions == [1]


@pytest.mark.parametrize('damage', ['missing', 'foreign', 'future', 'corrupt'])
def test_invalid_ready_library_prevents_writable_context_body(
    tmp_path: Path, damage: str
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    initialize_database_library(paths)
    if damage == 'missing':
        paths.database.unlink()
    elif damage == 'corrupt':
        paths.database.write_bytes(b'preserve corrupt database')
    else:
        with closing(connect(paths.database)) as connection:
            if damage == 'foreign':
                connection.execute('UPDATE meta SET library_id=?', (str(uuid4()),))
            else:
                connection.execute('UPDATE meta SET schema_version=99')
            connection.commit()
    before = {
        path: path.read_bytes() for path in paths.root.rglob('*') if path.is_file()
    }
    with pytest.raises(LibraryDatabaseError), prepare_database_download(paths):
        pytest.fail('Invalid storage cannot enter a writable download run')
    assert {
        path: path.read_bytes() for path in paths.root.rglob('*') if path.is_file()
    } == before
