"""Primary saved records preserve identity, independent observations and snapshots."""

from collections.abc import Generator
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from errno import EACCES, ENOSYS, EPERM
from os import stat_result
from pathlib import Path
from shutil import rmtree
from unittest.mock import Mock

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import SessionTransaction

from boosty_downloader.domain.library import LocatedPost, PostAccess
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.domain.stored_post import (
    LineBreak,
    ListBlock,
    ListItem,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.library._db_models import (
    DbAuthor,
    DbMarks,
    DbMedia,
    DbMediaMarks,
    DbPost,
    DbPostTag,
)
from boosty_downloader.infrastructure.library.db_post_records import DatabasePostRecords
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase
from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidPostRecordError,
)
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

NOW = datetime(2026, 10, 25, 12, 34, 56, 123456, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=7)
POST_ID = 'abcdefgh-first'
FOLDER = 'writer/2026-10-25 - Original (abcdefgh)'
SECOND_FOLDER = 'writer/2026-10-25 - Other (abcdefgh)'
MEDIA_ID = 'audio:lesson'


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'library'


@pytest.fixture
def database(tmp_path: Path) -> Generator[LibraryDatabase, None, None]:
    with LibraryDatabase.create(tmp_path / 'library.db') as database:
        yield database


@pytest.fixture
def store(root: Path, database: LibraryDatabase) -> DatabasePostRecords:
    return DatabasePostRecords(root, database)


@pytest.fixture
def record() -> StoredPost:
    return StoredPost(
        PostMetadata(
            POST_ID,
            'writer',
            f'https://boosty.to/writer/posts/{POST_ID}',
            'Original',
            NOW,
            NOW,
            tags=['lesson'],
            content_counters={'audio': 1},
        ),
        PostSync(NOW, NOW, page_template=2),
        [
            TextBlock([PostDataChunkText.TextFragment('Ёлка café')]),
            MediaBlock(MEDIA_ID),
        ],
        {
            MEDIA_ID: MediaEntry(
                MediaKind.audio,
                MediaStatus.downloaded,
                NOW,
                5,
                path='audio/lesson.mp3',
                size=42,
            )
        },
    )


def _post(database: LibraryDatabase) -> DbPost:
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        session.expunge(row)
        return row


def _seed_marks(database: LibraryDatabase) -> None:
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        session.add(DbMarks(post_row_id=row.id, seen_at=NOW, favorite=True))
        session.add(
            DbMediaMarks(
                post_row_id=row.id,
                media_id='future:retained',
                position=123.5,
                finished_at=NOW,
            )
        )


def _assert_marks(database: LibraryDatabase, *, present: bool) -> None:
    with database.transaction() as session:
        marks = session.scalar(select(DbMarks))
        playback = session.scalar(select(DbMediaMarks))
        if not present:
            assert marks is None
            assert playback is None
            return
        assert marks is not None
        assert marks.favorite
        assert marks.seen_at == NOW
        assert playback is not None
        assert playback.media_id == 'future:retained'
        assert playback.position == 123.5
        assert playback.finished_at == NOW


@pytest.mark.parametrize('adapter', [JsonPostRecords, DatabasePostRecords])
def test_common_saved_post_contract(
    adapter: type[JsonPostRecords] | type[DatabasePostRecords],
    root: Path,
    database: LibraryDatabase,
    record: StoredPost,
):
    store = (
        DatabasePostRecords(root, database)
        if adapter is DatabasePostRecords
        else JsonPostRecords(root)
    )
    assert store.find_post('writer', POST_ID) is None
    assert store.choose_post_folder(record.post) == FOLDER
    assert not root.exists()
    store.save_post(FOLDER, record)
    renamed = deepcopy(record)
    renamed.post.title = 'Renamed'
    store.save_post(FOLDER, renamed)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, renamed)
    other = replace(record, post=replace(record.post, id='abcdefgh-second'))
    other_folder = store.choose_post_folder(other.post)
    store.save_post(other_folder, other)
    assert store.find_post('writer', other.post.id) == LocatedPost(other_folder, other)
    assert store.find_post('writer', 'abcdefgh-third') is None


def test_roundtrip_retains_all_body_media_metadata_and_utc(
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
    database: LibraryDatabase,
):
    record.post.published_at = NOW
    record.post.tier = 'Research'
    record.post.tier_price_rub = 500.5
    record.post.post_price_rub = 123.25
    record.post.likes, record.post.comments = 7, 4
    record.sync.synced_at = LATER.astimezone(timezone(timedelta(hours=3)))
    record.blocks[:0] = [
        ParagraphBreak(),
        TextBlock([PostDataChunkText.TextFragment('Heading'), LineBreak()]),
        ListBlock(
            [
                ListItem(
                    [TextBlock([PostDataChunkText.TextFragment('Parent')])],
                    [ListItem([ParagraphBreak()])],
                )
            ],
            PostDataChunkTextualList.ListStyle.ordered,
        ),
    ]
    record.media[MEDIA_ID] = replace(
        record.media[MEDIA_ID],
        removed_at=LATER,
        title='Retained',
        filename='lesson.mp3',
        artist='Writer',
        duration=timedelta(seconds=3.125),
        width=640,
        height=480,
        preview_path='previews/lesson.jpg',
        thumbnail_path='.boosty-downloader/thumbs/lesson.jpg',
        error='Previous transfer error',
    )
    for position, (kind, status) in enumerate(zip(MediaKind, MediaStatus, strict=True)):
        media_id = f'{kind.value}:piece'
        entry = MediaEntry(
            kind, status, NOW, position, path=f'media/{position}.bin', size=position
        )
        record.media[media_id] = entry
        record.blocks.append(MediaBlock(media_id))
    original = deepcopy(record)
    store.save_post(FOLDER, record)
    found = store.find_post('writer', POST_ID)
    assert found == LocatedPost(FOLDER, original)
    assert found is not None
    assert found.record is not None
    assert found.record.sync.synced_at.tzinfo is timezone.utc
    assert record == original
    assert list((root / FOLDER).iterdir()) == []
    with database.transaction() as session:
        author = session.get(DbAuthor, 'writer')
        assert author is not None
        assert author.synced_at is None
        assert author.title is None
        assert session.execute(
            text("SELECT rowid FROM posts_fts WHERE posts_fts MATCH 'елка AND cafe'")
        ).all()


def test_saved_inputs_and_reads_are_detached(
    store: DatabasePostRecords, record: StoredPost
):
    expected = deepcopy(record)
    store.save_post(FOLDER, record)
    record.post.tags.append('input mutation')
    record.post.content_counters.clear()
    record.blocks.clear()
    record.media[MEDIA_ID].path = 'changed'
    first = store.find_post('writer', POST_ID)
    second = store.find_post('writer', POST_ID)
    assert first is not None
    assert first.record is not None
    assert second == LocatedPost(FOLDER, expected)
    first.record.post.tags.append('read mutation')
    first.record.post.content_counters.clear()
    first.record.blocks.clear()
    first.record.media[MEDIA_ID].path = 'other'
    assert second == LocatedPost(FOLDER, expected)
    assert store.find_post('writer', POST_ID) == second


def test_each_save_keeps_primary_identity_marks_and_removed_inventory(
    database: LibraryDatabase,
    store: DatabasePostRecords,
    record: StoredPost,
):
    store.save_post(FOLDER, record)
    original_id = _post(database).id
    _seed_marks(database)
    record.post.tags = ['new', 'new']
    record.media[MEDIA_ID].removed_at = LATER
    record.media[MEDIA_ID].status = MediaStatus.deleted
    record.sync.synced_at = LATER
    store.save_post(FOLDER, record)
    assert _post(database).id == original_id
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)
    _assert_marks(database, present=True)
    record.blocks.clear()
    record.media.clear()
    store.save_post(FOLDER, record)
    _assert_marks(database, present=True)
    with database.transaction() as session:
        assert list(session.scalars(select(DbMedia))) == []
        assert list(session.scalars(select(DbPostTag.tag))) == ['new']


def test_missing_folder_lookup_does_not_reset_marks_but_next_save_does(
    database: LibraryDatabase,
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
):
    store.save_post(FOLDER, record)
    _seed_marks(database)
    rmtree(root / FOLDER)
    assert store.find_post('writer', POST_ID) is None
    _assert_marks(database, present=True)
    record.blocks.clear()
    record.media.clear()
    record.sync.first_downloaded_at = LATER
    store.save_post(FOLDER, record)
    _assert_marks(database, present=False)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)


def _lock_overview(database: LibraryDatabase) -> None:
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        row.access = PostAccess.locked
        row.title = 'Locked title'
        row.tags = ['locked']
        row.likes = 999
        row.locked_synced_at = LATER
        row.teaser_path = '.boosty-downloader/teasers/preview.jpg'
        row.teaser_thumbnail_path = '.boosty-downloader/teasers/thumbnail.jpg'
        session.query(DbPostTag).delete()
        session.add(DbPostTag(post_row_id=row.id, tag='locked'))


@pytest.mark.parametrize('delete_folder', [False, True])
def test_saving_retained_body_preserves_independent_locked_overview(
    database: LibraryDatabase,
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
    *,
    delete_folder: bool,
):
    store.save_post(FOLDER, record)
    _seed_marks(database)
    _lock_overview(database)
    if delete_folder:
        rmtree(root / FOLDER)
    record.post.title = 'Saved title'
    record.post.tags = ['saved']
    record.blocks[0] = TextBlock([PostDataChunkText.TextFragment('Updated body')])
    store.save_post(FOLDER, record)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)
    row = _post(database)
    assert row.access == PostAccess.locked
    assert row.title == 'Locked title'
    assert row.tags == ['locked']
    assert row.likes == 999
    assert row.locked_synced_at == LATER
    assert row.teaser_path == '.boosty-downloader/teasers/preview.jpg'
    assert row.teaser_thumbnail_path == '.boosty-downloader/teasers/thumbnail.jpg'
    assert row.body_text == 'Updated body'
    _assert_marks(database, present=not delete_folder)
    with database.transaction() as session:
        assert list(session.scalars(select(DbPostTag.tag))) == ['locked']


def test_locked_only_record_is_not_a_downloaded_post(
    database: LibraryDatabase,
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
):
    store.save_post(FOLDER, record)
    _lock_overview(database)
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        row.folder = row.saved_metadata = row.blocks = row.origin = None
        row.first_downloaded_at = row.synced_at = row.page_template = None
        session.query(DbMedia).delete()
    rmtree(root / FOLDER)
    assert store.find_post('writer', POST_ID) is None
    store.save_post(FOLDER, record)
    assert _post(database).access == PostAccess.locked
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)


@pytest.mark.parametrize(
    'invalid', ['missing-reference', 'wrong-kind', 'negative', 'escape', 'nan', 'naive']
)
def test_invalid_record_is_rejected_before_any_write(
    database: LibraryDatabase,
    root: Path,
    record: StoredPost,
    invalid: str,
    monkeypatch: pytest.MonkeyPatch,
):
    store = DatabasePostRecords(root, database)
    match invalid:
        case 'missing-reference':
            record.media.clear()
        case 'wrong-kind':
            record.media[MEDIA_ID].kind = MediaKind.file
        case 'negative':
            record.media[MEDIA_ID].position = -1
        case 'escape':
            record.media[MEDIA_ID].path = '../escape'
        case 'nan':
            record.post.tier_price_rub = float('nan')
        case 'naive':
            record.sync.synced_at = NOW.replace(tzinfo=None)
        case _:
            pytest.fail(f'Unknown invalid record case: {invalid}')
    transaction = Mock(side_effect=AssertionError('write transaction opened'))
    monkeypatch.setattr(database, 'transaction', transaction)
    with pytest.raises(InvalidPostRecordError):
        store.save_post(FOLDER, record)
    transaction.assert_not_called()
    assert not root.exists()


def test_database_cross_field_corruption_is_not_returned_as_a_valid_post(
    database: LibraryDatabase,
    store: DatabasePostRecords,
    record: StoredPost,
):
    store.save_post(FOLDER, record)
    with database.transaction() as session:
        session.query(DbMedia).delete()
    with pytest.raises(
        InvalidPostRecordError, match='missing from the media inventory'
    ):
        store.find_post('writer', POST_ID)


def test_database_saved_metadata_identity_cannot_override_full_row_identity(
    database: LibraryDatabase,
    store: DatabasePostRecords,
    record: StoredPost,
):
    store.save_post(FOLDER, record)
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        row.saved_metadata = replace(record.post, id='abcdefgh-foreign')
    with pytest.raises(InvalidPostRecordError, match='identity disagrees'):
        store.find_post('writer', POST_ID)


def test_read_methods_never_open_a_writer_and_do_not_create_the_library(
    database: LibraryDatabase,
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
    monkeypatch: pytest.MonkeyPatch,
):
    transaction = Mock(side_effect=AssertionError('writer opened'))
    monkeypatch.setattr(database, 'transaction', transaction)
    original = database.path.read_bytes()
    assert store.find_post('writer', POST_ID) is None
    assert store.choose_post_folder(record.post, reserved_folders=[FOLDER]) == (
        'writer/2026-10-25 - Original [2] (abcdefgh)'
    )
    transaction.assert_not_called()
    assert not root.exists()
    assert database.path.read_bytes() == original


def test_rollback_removes_recreated_empty_folder_without_reviving_stale_generation(
    database: LibraryDatabase,
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
    monkeypatch: pytest.MonkeyPatch,
):
    store.save_post(FOLDER, record)
    _seed_marks(database)
    rmtree(root / FOLDER)
    old_row = _post(database)
    record.post.title = 'Uncommitted'
    commit = Mock(side_effect=OSError('Commit failed'))
    monkeypatch.setattr(SessionTransaction, 'commit', commit)
    with pytest.raises(OSError, match='Commit failed'):
        store.save_post(FOLDER, record)
    monkeypatch.undo()
    assert not (root / FOLDER).exists()
    assert store.find_post('writer', POST_ID) is None
    assert _post(database).title == old_row.title
    _assert_marks(database, present=True)


def test_rollback_preserves_existing_directory_and_files(
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
    monkeypatch: pytest.MonkeyPatch,
):
    target = root / FOLDER
    target.mkdir(parents=True)
    media = target / 'retained.bin'
    media.write_bytes(b'user file')
    monkeypatch.setattr(
        SessionTransaction, 'commit', Mock(side_effect=OSError('Commit failed'))
    )
    with pytest.raises(OSError, match='Commit failed'):
        store.save_post(FOLDER, record)
    assert media.read_bytes() == b'user file'


def test_paths_remain_portable_after_relocating_the_library(
    tmp_path: Path,
    record: StoredPost,
):
    root = tmp_path / 'source'
    with LibraryDatabase.create(root / 'library.db') as database:
        DatabasePostRecords(root, database).save_post(FOLDER, record)
    moved = tmp_path / 'moved'
    root.rename(moved)
    with LibraryDatabase.open(moved / 'library.db') as database:
        assert DatabasePostRecords(moved, database).find_post(
            'writer', POST_ID
        ) == LocatedPost(FOLDER, record)


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except NotImplementedError:
        pytest.skip('Filesystem does not support symlinks')
    except OSError as error:
        if (
            error.errno in {EPERM, EACCES, ENOSYS}
            or getattr(error, 'winerror', None) == 1314
        ):
            pytest.skip('Filesystem does not permit symlinks')
        raise


def test_safe_aliases_normalize_and_cannot_bypass_folder_ownership(
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
):
    target = root / FOLDER
    target.mkdir(parents=True)
    _symlink(root / SECOND_FOLDER, target)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER)
    store.save_post(SECOND_FOLDER, record)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)
    other = replace(record, post=replace(record.post, id='abcdefgh-second'))
    assert store.find_post('writer', other.post.id) is None
    with pytest.raises(ValueError, match='belongs to another post'):
        store.save_post(SECOND_FOLDER, other)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)


@pytest.mark.parametrize(
    'redirect',
    ['outside', 'different-author', 'different-layout', 'different-id', 'dangling'],
)
def test_aliases_cannot_redirect_author_or_post_layout(
    tmp_path: Path,
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
    redirect: str,
):
    (root / 'writer').mkdir(parents=True)
    match redirect:
        case 'outside':
            target = tmp_path / 'outside'
        case 'different-author':
            target = root / 'other' / Path(FOLDER).name
        case 'different-layout':
            target = root / 'writer' / 'nested' / Path(FOLDER).name
        case 'different-id':
            target = root / 'writer' / '2026-10-25 - Other (different)'
        case _:
            target = root / SECOND_FOLDER
    if redirect != 'dangling':
        target.mkdir(parents=True)
    _symlink(root / FOLDER, target)
    with pytest.raises((ValueError, FileNotFoundError)):
        store.save_post(FOLDER, record)
    with pytest.raises((ValueError, FileNotFoundError)):
        store.find_post('writer', POST_ID)


def test_missing_folder_ownership_is_rechecked_by_each_writer(
    root: Path,
    database: LibraryDatabase,
    store: DatabasePostRecords,
    record: StoredPost,
):
    other = replace(record, post=replace(record.post, id='abcdefgh-second'))
    stale_choice = store.choose_post_folder(other.post)
    second = DatabasePostRecords(root, database)
    second.save_post(stale_choice, record)
    with pytest.raises(ValueError, match='belongs to another post'):
        store.save_post(stale_choice, other)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)


def test_exact_full_id_wins_and_unowned_candidates_never_import_json(
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
):
    (root / SECOND_FOLDER).mkdir(parents=True)
    (root / SECOND_FOLDER / 'post.json').write_bytes(b'not valid JSON')
    assert store.find_post('writer', POST_ID) == LocatedPost(SECOND_FOLDER)
    store.save_post(FOLDER, record)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)
    assert store.find_post('writer', 'abcdefgh-second') == LocatedPost(SECOND_FOLDER)
    third = root / 'writer/2026-10-25 - Third (abcdefgh)'
    third.mkdir()
    with pytest.raises(AmbiguousPostFolderError):
        store.find_post('writer', 'abcdefgh-third')


@pytest.mark.parametrize('replacement', ['file', 'permission'])
def test_filesystem_failures_never_reset_a_saved_generation(
    root: Path,
    database: LibraryDatabase,
    record: StoredPost,
    replacement: str,
    monkeypatch: pytest.MonkeyPatch,
):
    store = DatabasePostRecords(root, database)
    store.save_post(FOLDER, record)
    _seed_marks(database)
    target = root / FOLDER
    if replacement == 'file':
        target.rmdir()
        target.write_bytes(b'user file')
    else:
        original = Path.lstat

        def unavailable(path: Path) -> stat_result:
            if path == target:
                message = 'Cannot inspect post'
                raise PermissionError(message)
            return original(path)

        monkeypatch.setattr(Path, 'lstat', unavailable)
    with pytest.raises((NotADirectoryError, PermissionError)):
        store.save_post(FOLDER, record)
    monkeypatch.undo()
    _assert_marks(database, present=True)
    assert _post(database).saved_metadata == record.post


@pytest.mark.parametrize('alias_title', ['original', 'Cafe\u0301'])
def test_physical_case_and_unicode_aliases_cannot_own_a_second_post(
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
    alias_title: str,
):
    title = 'Original' if alias_title == 'original' else 'Café'
    folder = FOLDER.replace('Original', title)
    alias = FOLDER.replace('Original', alias_title)
    record.post.title = title
    store.save_post(folder, record)
    if not (root / alias).exists() or not (root / alias).samefile(root / folder):
        pytest.skip('Filesystem distinguishes these directory spellings')
    other = replace(record, post=replace(record.post, id='abcdefgh-second'))
    with pytest.raises(ValueError, match='belongs to another post'):
        store.save_post(alias, other)
    assert store.find_post('writer', POST_ID) == LocatedPost(folder, record)
    assert store.find_post('writer', other.post.id) is None


def test_reservations_compare_portable_spellings_before_folders_exist(
    store: DatabasePostRecords,
    record: StoredPost,
):
    record.post.title = 'original'
    assert store.choose_post_folder(record.post, reserved_folders=[FOLDER]) == (
        'writer/2026-10-25 - original [2] (abcdefgh)'
    )
    record.post.title = 'Cafe\u0301'
    assert store.choose_post_folder(
        record.post, reserved_folders=[FOLDER.replace('Original', 'Café')]
    ) == ('writer/2026-10-25 - Café [2] (abcdefgh)')


def test_deleted_folder_keeps_its_portable_identity_reserved(
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
):
    store.save_post(FOLDER, record)
    rmtree(root / FOLDER)
    other = replace(
        record, post=replace(record.post, id='abcdefgh-second', title='original')
    )
    assert (
        store.choose_post_folder(other.post)
        == 'writer/2026-10-25 - original [2] (abcdefgh)'
    )
    with pytest.raises(ValueError, match='belongs to another post'):
        store.save_post(FOLDER.replace('Original', 'original'), other)
    assert store.find_post('writer', POST_ID) is None


def test_deleted_author_directory_cannot_change_its_portable_identity(
    root: Path,
    store: DatabasePostRecords,
    record: StoredPost,
):
    store.save_post(FOLDER, record)
    rmtree(root / 'writer')
    alias = replace(record, post=replace(record.post, author='Writer'))
    with pytest.raises(ValueError, match='Author spelling aliases'):
        store.choose_post_folder(alias.post)
    with pytest.raises(ValueError, match='Author spelling aliases'):
        store.save_post(FOLDER.replace('writer/', 'Writer/'), alias)
    with pytest.raises(ValueError, match='Author spelling aliases'):
        store.find_post('Writer', POST_ID)
    assert not (root / 'writer').exists()


def test_publication_failure_keeps_new_snapshot_hidden_until_retry(
    root: Path,
    database: LibraryDatabase,
    record: StoredPost,
    monkeypatch: pytest.MonkeyPatch,
):
    store = DatabasePostRecords(root, database)
    store.save_post(FOLDER, record)
    _seed_marks(database)
    rmtree(root / FOLDER)
    record.post.title = 'New generation'
    original_mkdir = Path.mkdir

    def unavailable(
        path: Path, mode: int = 0o777, *, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == root / FOLDER:
            message = 'Cannot publish post folder'
            raise PermissionError(message)
        original_mkdir(path, mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, 'mkdir', unavailable)
    with pytest.raises(PermissionError, match='Cannot publish'):
        store.save_post(FOLDER, record)
    monkeypatch.undo()
    assert store.find_post('writer', POST_ID) is None
    assert _post(database).saved_metadata == record.post
    _assert_marks(database, present=False)
    store.save_post(FOLDER, record)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)
    _assert_marks(database, present=False)


def test_full_post_id_is_scoped_by_author_and_existing_author_metadata_survives(
    database: LibraryDatabase,
    store: DatabasePostRecords,
    record: StoredPost,
):
    with database.transaction() as session:
        session.add(DbAuthor(author='writer', title='Known blog', synced_at=NOW))
    store.save_post(FOLDER, record)
    other = replace(record, post=replace(record.post, author='other-writer'))
    other_folder = store.choose_post_folder(other.post)
    store.save_post(other_folder, other)
    assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)
    assert store.find_post('other-writer', POST_ID) == LocatedPost(other_folder, other)
    with database.transaction() as session:
        author = session.get(DbAuthor, 'writer')
        assert author is not None
        assert author.title == 'Known blog'
        assert author.synced_at == NOW


def test_lookup_and_choice_read_committed_snapshot_while_writer_holds_lock(
    database: LibraryDatabase,
    store: DatabasePostRecords,
    record: StoredPost,
):
    store.save_post(FOLDER, record)
    with database.transaction() as session:
        row = session.scalars(select(DbPost)).one()
        row.saved_metadata = replace(record.post, title='Uncommitted')
        session.flush()
        assert store.find_post('writer', POST_ID) == LocatedPost(FOLDER, record)
        assert (
            store.choose_post_folder(record.post)
            == 'writer/2026-10-25 - Original [2] (abcdefgh)'
        )
