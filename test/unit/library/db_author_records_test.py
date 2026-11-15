"""Database metadata transitions retain saved generations and independent marks."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from shutil import rmtree
from typing import TYPE_CHECKING, TypeAlias
from unittest.mock import Mock

import pytest
from sqlalchemy import event, select, text

from boosty_downloader.domain.library import LocatedPost, PostAccess
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.library._db_models import (
    DbAuthor,
    DbMarks,
    DbMediaMarks,
    DbPost,
)
from boosty_downloader.infrastructure.library.db_author_records import (
    DatabaseAuthorRecords,
)
from boosty_downloader.infrastructure.library.db_post_store import DatabasePostStore
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase
from boosty_downloader.infrastructure.library.errors import InvalidAuthorRecordError

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from sqlalchemy import Connection

    from boosty_downloader.application.ports import PostStore

NOW = datetime(2026, 11, 15, 12, 34, 56, 123456, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=7)
POST_ID = 'abcdefgh-first'
MEDIA_ID = 'audio:retained'
FOLDER = 'writer/2026-11-15 - Saved title (abcdefgh)'
DatabaseRows: TypeAlias = dict[str, list[dict[str, object]]]


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'library'


@pytest.fixture
def database(tmp_path: Path) -> Generator[LibraryDatabase, None, None]:
    with LibraryDatabase.create(tmp_path / 'library.db') as database:
        yield database


@pytest.fixture
def authors(root: Path, database: LibraryDatabase) -> DatabaseAuthorRecords:
    return DatabaseAuthorRecords(root, database)


@pytest.fixture
def store(root: Path, database: LibraryDatabase) -> PostStore:
    return DatabasePostStore(root, database)


@pytest.fixture
def author() -> AuthorInfo:
    return AuthorInfo(
        'writer',
        NOW,
        title='Known blog',
        owner_name='Fixture writer',
        description='First paragraph\n\nSecond paragraph',
        avatar_path='.boosty-downloader/avatar.jpg',
        cover_path='.boosty-downloader/cover.png',
        remote_post_count=42,
    )


@pytest.fixture
def saved() -> StoredPost:
    return StoredPost(
        PostMetadata(
            POST_ID,
            'writer',
            'https://boosty.to/writer/posts/fixture',
            'Saved title',
            NOW,
            NOW,
            tags=['saved'],
            content_counters={'audio': 1},
        ),
        PostSync(NOW, NOW, page_template=4),
        [
            TextBlock([PostDataChunkText.TextFragment('saveddurableword')]),
            MediaBlock(MEDIA_ID),
        ],
        {
            MEDIA_ID: MediaEntry(
                MediaKind.audio,
                MediaStatus.downloaded,
                NOW,
                7,
                removed_at=LATER,
                path='audio/retained.mp3',
                size=123,
                duration=timedelta(seconds=12.5),
            )
        },
    )


@pytest.fixture
def locked(saved: StoredPost) -> LockedPost:
    return LockedPost(
        replace(
            saved.post,
            url='https://boosty.to/writer/posts/observation',
            title='lockedsearchword',
            updated_at=LATER,
            published_at=LATER,
            tags=['locked', 'locked'],
            tier='Research',
            tier_price_rub=501.25,
            post_price_rub=123.75,
            likes=17,
            comments=3,
            content_counters={'audio': 4, 'image': 2},
        ),
        LATER,
        teaser_path='.boosty-downloader/teasers/lesson.jpg',
        teaser_thumbnail_path='.boosty-downloader/thumbs/lesson.jpg',
    )


def _database_rows(database: LibraryDatabase) -> DatabaseRows:
    statements = {
        'authors': 'SELECT * FROM authors ORDER BY author',
        'posts': 'SELECT * FROM posts ORDER BY id',
        'media': 'SELECT * FROM media ORDER BY post_row_id, media_id',
        'tags': 'SELECT * FROM post_tags ORDER BY post_row_id, tag',
        'marks': 'SELECT * FROM marks ORDER BY post_row_id',
        'playback': 'SELECT * FROM media_marks ORDER BY post_row_id, media_id',
        'fts': 'SELECT rowid, * FROM posts_fts ORDER BY rowid',
    }
    with database.engine.connect() as connection:
        return {
            name: [dict(row) for row in connection.execute(text(query)).mappings()]
            for name, query in statements.items()
        }


def _seed_marks(database: LibraryDatabase) -> None:
    with database.transaction() as session:
        post = session.scalars(select(DbPost)).one()
        session.add(DbMarks(post_row_id=post.id, favorite=True, seen_at=NOW))
        session.add(
            DbMediaMarks(
                post_row_id=post.id,
                media_id='future:missing',
                position=42.125,
                finished_at=NOW,
            )
        )


def _search(database: LibraryDatabase, term: str) -> list[int]:
    with database.engine.connect() as connection:
        return list(
            connection.execute(
                text('SELECT rowid FROM posts_fts WHERE posts_fts MATCH :term'),
                {'term': term},
            ).scalars()
        )


def test_metadata_writes_create_no_asset_folders_or_json_sidecars(
    root: Path,
    authors: DatabaseAuthorRecords,
    author: AuthorInfo,
    locked: LockedPost,
):
    authors.save_author(author)
    authors.save_locked_post(locked)
    assert authors.load_author(author.author) == author
    assert authors.load_locked_post(author.author, POST_ID) == locked
    assert not root.exists()
    authors.clear_locked_post(author.author, POST_ID)
    assert authors.load_author(author.author) == author
    assert not root.exists()


def test_post_placeholder_becomes_full_author_without_replacing_parent_row(
    database: LibraryDatabase,
    store: PostStore,
    saved: StoredPost,
    author: AuthorInfo,
):
    store.save_post(FOLDER, saved)
    _seed_marks(database)
    assert store.load_author('writer') is None
    before = _database_rows(database)
    store.save_author(author)
    after = _database_rows(database)
    assert store.load_author('writer') == author
    for table in ('posts', 'media', 'tags', 'marks', 'playback', 'fts'):
        assert after[table] == before[table]


def test_author_replacements_normalize_utc_and_preserve_all_asset_bytes(
    root: Path,
    authors: DatabaseAuthorRecords,
    author: AuthorInfo,
):
    avatar = root / 'writer' / '.boosty-downloader/avatar.jpg'
    avatar.parent.mkdir(parents=True)
    avatar.write_bytes(b'kept image')
    modified = avatar.stat().st_mtime_ns
    author.synced_at = NOW.astimezone(timezone(timedelta(hours=3)))
    expected = deepcopy(author)
    authors.save_author(author)
    assert author == expected
    loaded = authors.load_author('writer')
    assert loaded is not None
    assert loaded.synced_at.tzinfo is timezone.utc
    authors.save_author(AuthorInfo('writer', LATER))
    assert authors.load_author('writer') == AuthorInfo('writer', LATER)
    assert avatar.read_bytes() == b'kept image'
    assert avatar.stat().st_mtime_ns == modified


def test_saved_locked_offline_update_clear_restores_latest_saved_overview(
    database: LibraryDatabase,
    store: PostStore,
    saved: StoredPost,
    locked: LockedPost,
):
    store.save_post(FOLDER, saved)
    _seed_marks(database)
    before = _database_rows(database)
    store.save_locked_post(locked)
    locked_rows = _database_rows(database)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, saved)
    assert store.load_locked_post('writer', POST_ID) == locked
    assert _search(database, 'lockedsearchword saveddurableword')
    for table in ('media', 'marks', 'playback'):
        assert locked_rows[table] == before[table]
    assert locked_rows['posts'][0]['id'] == before['posts'][0]['id']
    assert (
        locked_rows['posts'][0]['saved_metadata']
        == before['posts'][0]['saved_metadata']
    )
    assert locked_rows['tags'] == [
        {'post_row_id': before['posts'][0]['id'], 'tag': 'locked'}
    ]
    saved.post.title = 'restoredsearchword'
    saved.post.tags = ['offline', 'offline']
    saved.post.content_counters = {'audio': 8}
    saved.sync.synced_at = LATER
    store.save_post(FOLDER, saved)
    assert store.load_locked_post('writer', POST_ID) == locked
    store.clear_locked_post('writer', POST_ID)
    after = _database_rows(database)
    assert store.load_locked_post('writer', POST_ID) is None
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, saved)
    assert _search(database, 'lockedsearchword') == []
    assert _search(database, 'restoredsearchword saveddurableword')
    for table in ('media', 'marks', 'playback'):
        assert after[table] == before[table]
    post = after['posts'][0]
    assert post['id'] == before['posts'][0]['id']
    assert post['access'] == PostAccess.open.value
    assert post['locked_synced_at'] is None
    assert post['teaser_path'] is None
    assert post['teaser_thumbnail_path'] is None
    assert post['title'] == saved.post.title
    assert after['tags'] == [{'post_row_id': post['id'], 'tag': 'offline'}]


def test_access_operations_keep_missing_saved_generation_and_marks(
    root: Path,
    database: LibraryDatabase,
    store: PostStore,
    saved: StoredPost,
    locked: LockedPost,
):
    store.save_post(FOLDER, saved)
    _seed_marks(database)
    before = _database_rows(database)
    rmtree(root / FOLDER)
    store.save_locked_post(locked)
    store.clear_locked_post('writer', POST_ID)
    assert store.find_post('writer', POST_ID) is None
    assert _database_rows(database) == before
    assert not (root / FOLDER).exists()


def test_locked_only_clear_removes_observation_tags_fts_but_retains_author(
    database: LibraryDatabase,
    authors: DatabaseAuthorRecords,
    locked: LockedPost,
):
    authors.save_locked_post(locked)
    before = _database_rows(database)
    post = before['posts'][0]
    assert post['folder'] is None
    assert post['saved_metadata'] is None
    assert post['blocks_json'] is None
    assert post['body_text'] == ''
    assert before['media'] == []
    assert authors.load_author('writer') is None
    authors.clear_locked_post('writer', POST_ID)
    after = _database_rows(database)
    assert after['authors'] == before['authors']
    for table in ('posts', 'media', 'tags', 'marks', 'playback', 'fts'):
        assert after[table] == []


@pytest.mark.parametrize('mark_table', ['post', 'media'])
def test_inconsistent_locked_only_marks_prevent_destructive_clear(
    database: LibraryDatabase,
    authors: DatabaseAuthorRecords,
    locked: LockedPost,
    mark_table: str,
):
    authors.save_locked_post(locked)
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        if mark_table == 'post':
            session.add(DbMarks(post_row_id=row.id, favorite=False))
        else:
            session.add(
                DbMediaMarks(
                    post_row_id=row.id, media_id='future:unknown', position=0.0
                )
            )
    before = _database_rows(database)
    with pytest.raises(InvalidAuthorRecordError, match='saved user marks'):
        authors.clear_locked_post('writer', POST_ID)
    assert _database_rows(database) == before
    assert authors.load_locked_post('writer', POST_ID) == locked


@pytest.mark.parametrize(
    'action', ['save-author', 'save-locked', 'clear-saved', 'clear-only']
)
def test_transaction_failure_preserves_all_rows_marks_tags_and_fts(
    database: LibraryDatabase,
    store: PostStore,
    author: AuthorInfo,
    locked: LockedPost,
    action: str,
):
    saved = StoredPost(replace(locked.post, title='Saved title'), PostSync(NOW, NOW))
    if action != 'clear-only':
        store.save_post(FOLDER, saved)
        _seed_marks(database)
    store.save_author(author)
    store.save_locked_post(locked)
    before = _database_rows(database)

    def fail_commit(_connection: Connection) -> None:
        message = 'Injected transaction failure'
        raise OSError(message)

    event.listen(database.engine, 'commit', fail_commit)
    try:
        with pytest.raises(OSError, match='Injected transaction failure'):
            _perform_transition(store, author, locked, action)
    finally:
        event.remove(database.engine, 'commit', fail_commit)
    assert _database_rows(database) == before
    assert _search(database, 'Interrupted') == []
    assert _search(database, 'lockedsearchword')


def _perform_transition(
    store: PostStore, author: AuthorInfo, locked: LockedPost, action: str
) -> None:
    match action:
        case 'save-author':
            store.save_author(replace(author, title='Interrupted'))
        case 'save-locked':
            store.save_locked_post(
                replace(
                    locked,
                    post=replace(
                        locked.post, title='Interrupted', tags=['interrupted']
                    ),
                )
            )
        case _:
            store.clear_locked_post('writer', POST_ID)


@pytest.mark.parametrize(
    'invalid', ['naive', 'negative-count', 'boolean-count', 'escape']
)
def test_author_validation_precedes_write_transaction(
    root: Path,
    database: LibraryDatabase,
    author: AuthorInfo,
    invalid: str,
    monkeypatch: pytest.MonkeyPatch,
):
    match invalid:
        case 'naive':
            author.synced_at = NOW.replace(tzinfo=None)
        case 'negative-count':
            author.remote_post_count = -1
        case 'boolean-count':
            author.remote_post_count = True
        case 'escape':
            author.avatar_path = '../escape'
        case _:
            pytest.fail(f'Unknown case {invalid}')
    transaction = Mock(side_effect=AssertionError('Writer opened'))
    monkeypatch.setattr(database, 'transaction', transaction)
    with pytest.raises(InvalidAuthorRecordError):
        DatabaseAuthorRecords(root, database).save_author(author)
    transaction.assert_not_called()
    assert not root.exists()


@pytest.mark.parametrize(
    'invalid',
    ['naive', 'negative-price', 'infinite-price', 'empty-id', 'thumbnail', 'counter'],
)
def test_locked_validation_precedes_write_transaction(
    root: Path,
    database: LibraryDatabase,
    locked: LockedPost,
    invalid: str,
    monkeypatch: pytest.MonkeyPatch,
):
    match invalid:
        case 'naive':
            locked.post.updated_at = NOW.replace(tzinfo=None)
        case 'negative-price':
            locked.post.post_price_rub = -1
        case 'infinite-price':
            locked.post.tier_price_rub = float('inf')
        case 'empty-id':
            locked.post.id = ''
        case 'thumbnail':
            locked.teaser_thumbnail_path = 'teasers/not-a-thumbnail.jpg'
        case 'counter':
            locked.post.content_counters['image'] = -1
        case _:
            pytest.fail(f'Unknown case {invalid}')
    transaction = Mock(side_effect=AssertionError('Writer opened'))
    monkeypatch.setattr(database, 'transaction', transaction)
    with pytest.raises(InvalidAuthorRecordError):
        DatabaseAuthorRecords(root, database).save_locked_post(locked)
    transaction.assert_not_called()
    assert not root.exists()


@pytest.mark.parametrize('corruption', ['partial-placeholder', 'unsafe-path'])
def test_invalid_author_row_is_not_read_as_missing_or_repaired_on_save(
    database: LibraryDatabase,
    authors: DatabaseAuthorRecords,
    author: AuthorInfo,
    corruption: str,
):
    authors.save_author(author)
    with database.transaction() as session:
        row = session.get(DbAuthor, 'writer')
        assert row is not None
        if corruption == 'partial-placeholder':
            row.synced_at = None
        else:
            row.avatar_path = '../escape'
    before = _database_rows(database)
    with pytest.raises(InvalidAuthorRecordError):
        authors.load_author('writer')
    with pytest.raises(InvalidAuthorRecordError):
        authors.save_author(author)
    assert _database_rows(database) == before


def test_invalid_locked_row_is_not_silently_repaired_or_deleted(
    database: LibraryDatabase,
    authors: DatabaseAuthorRecords,
    locked: LockedPost,
):
    authors.save_locked_post(locked)
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        row.teaser_path = '../escape'
    before = _database_rows(database)
    with pytest.raises(InvalidAuthorRecordError):
        authors.load_locked_post('writer', POST_ID)
    with pytest.raises(InvalidAuthorRecordError):
        authors.save_locked_post(locked)
    with pytest.raises(InvalidAuthorRecordError):
        authors.clear_locked_post('writer', POST_ID)
    assert _database_rows(database) == before


def test_saved_identity_mismatch_blocks_restoring_the_wrong_overview(
    database: LibraryDatabase,
    store: PostStore,
    saved: StoredPost,
    locked: LockedPost,
):
    store.save_post(FOLDER, saved)
    store.save_locked_post(locked)
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        row.saved_metadata = replace(saved.post, id='abcdefgh-other')
    before = _database_rows(database)
    with pytest.raises(
        InvalidAuthorRecordError, match='disagrees with the post identity'
    ):
        store.clear_locked_post('writer', POST_ID)
    assert _database_rows(database) == before


def test_reads_use_committed_snapshots_while_a_writer_holds_the_lock(
    database: LibraryDatabase,
    authors: DatabaseAuthorRecords,
    author: AuthorInfo,
    locked: LockedPost,
):
    authors.save_author(author)
    authors.save_locked_post(locked)
    with database.transaction() as session:
        row = session.get(DbAuthor, 'writer')
        assert row is not None
        row.title = 'Uncommitted author'
        post = session.scalars(select(DbPost)).one()
        post.title = 'Uncommitted title'
        session.flush()
        assert authors.load_author('writer') == author
        assert authors.load_locked_post('writer', POST_ID) == locked


def test_portable_author_aliases_are_rejected_even_without_directories(
    root: Path,
    authors: DatabaseAuthorRecords,
    author: AuthorInfo,
    locked: LockedPost,
):
    authors.save_author(author)
    alias = replace(author, author='Writer')
    with pytest.raises(ValueError, match='Author spelling aliases'):
        authors.save_author(alias)
    with pytest.raises(ValueError, match='Author spelling aliases'):
        authors.load_author('Writer')
    with pytest.raises(ValueError, match='Author spelling aliases'):
        authors.save_locked_post(
            replace(locked, post=replace(locked.post, author='Writer'))
        )
    with pytest.raises(ValueError, match='Author spelling aliases'):
        authors.load_locked_post('Writer', POST_ID)
    with pytest.raises(ValueError, match='Author spelling aliases'):
        authors.clear_locked_post('Writer', POST_ID)
    assert not root.exists()
