"""The JSON PostStore preserves saved content across changes in live access."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import rmtree
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
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
from boosty_downloader.infrastructure.library.author_records import (
    read_author_record,
    read_locked_posts,
)
from boosty_downloader.infrastructure.library.post_marks import (
    VIEWER_RECORD_FILENAME,
    JsonPostMarks,
)
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from collections.abc import Iterable

    from boosty_downloader.application.ports import PostStore

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=7)
POST_ID = 'abcdefgh-first'
MEDIA_ID = 'file:lesson'
MEDIA_BYTES = b'Saved lesson file'
AUDIO_ID = 'audio:lesson'
AUDIO_BYTES = b'Saved lesson audio'


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    data: bytes
    modified_ns: int


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'library'


@pytest.fixture
def store(root: Path) -> PostStore:
    return JsonPostStore(root)


@pytest.fixture
def record() -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            id=POST_ID,
            author='writer',
            url=f'https://boosty.to/writer/posts/{POST_ID}',
            title='Original lesson',
            created_at=NOW,
            updated_at=NOW,
            tags=['lesson'],
            content_counters={'file': 1, 'audio': 1},
        ),
        sync=PostSync(NOW, NOW, page_template=1),
        blocks=[
            TextBlock([PostDataChunkText.TextFragment('Saved body')]),
            MediaBlock(MEDIA_ID),
            MediaBlock(AUDIO_ID),
        ],
        media={
            MEDIA_ID: MediaEntry(
                kind=MediaKind.file,
                status=MediaStatus.downloaded,
                added_at=NOW,
                position=0,
                path='files/lesson.zip',
                size=len(MEDIA_BYTES),
            ),
            AUDIO_ID: MediaEntry(
                kind=MediaKind.audio,
                status=MediaStatus.downloaded,
                added_at=NOW,
                position=1,
                path='audio/lesson.mp3',
                size=len(AUDIO_BYTES),
            ),
        },
    )


@pytest.fixture
def marks() -> PostMarks:
    return PostMarks(
        seen_at=NOW, favorite=True, positions={AUDIO_ID: PlaybackPosition(42.5, NOW)}
    )


def _snapshot(paths: Iterable[Path]) -> dict[Path, FileSnapshot]:
    return {
        path: FileSnapshot(path.read_bytes(), path.stat().st_mtime_ns) for path in paths
    }


def _seed_retained_files(root: Path, folder: str, marks: PostMarks) -> list[Path]:
    files = {
        root / folder / 'files/lesson.zip': MEDIA_BYTES,
        root / folder / 'audio/lesson.mp3': AUDIO_BYTES,
        root / folder / 'post.html': b'<p>Saved page</p>',
        root / 'writer/.boosty-downloader/avatar.jpg': b'avatar',
        root / 'writer/.boosty-downloader/cover.png': b'cover',
        root / f'writer/.boosty-downloader/teasers/{POST_ID}.jpg': b'teaser',
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    JsonPostMarks(root).save_marks('writer', POST_ID, marks)
    return [*files, root / folder / VIEWER_RECORD_FILENAME]


def test_lookup_choice_and_absent_clear_do_not_create_a_library(
    root: Path, store: PostStore, record: StoredPost
):
    assert not root.exists()
    assert store.find_post('writer', POST_ID) is None
    assert store.choose_post_folder(record.post) == (
        'writer/2026-10-25 - Original lesson (abcdefgh)'
    )
    store.clear_locked_post('writer', POST_ID)
    assert not root.exists()


def test_locked_only_post_gets_a_body_before_explicit_access_clear(
    root: Path, store: PostStore, record: StoredPost
):
    author = AuthorInfo('writer', NOW, title='Lessons')
    locked = LockedPost(record.post, NOW)
    store.save_author(author=author)
    store.save_locked_post(locked)
    assert store.find_post('writer', POST_ID) is None
    assert {path.name for path in (root / 'writer').iterdir()} == {'.boosty-downloader'}

    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)

    assert store.find_post('writer', POST_ID) == LocatedPost(folder, record)
    assert read_locked_posts(root, 'writer') == {POST_ID: locked}
    assert read_author_record(root, 'writer') == author
    store.clear_locked_post('writer', POST_ID)
    assert read_locked_posts(root, 'writer') == {}
    assert JsonPostStore(root).find_post('writer', POST_ID) == LocatedPost(
        folder, record
    )


def test_lost_access_and_offline_resave_preserve_content_and_marks(
    root: Path, store: PostStore, record: StoredPost, marks: PostMarks
):
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    retained = _seed_retained_files(root, folder, marks)
    before_files = _snapshot(retained)
    post_file = root / folder / 'post.json'
    before_record = _snapshot([post_file])
    locked = LockedPost(record.post, LATER)
    other = LockedPost(replace(record.post, id='abcdefgh-second'), LATER)

    store.save_locked_post(locked)
    store.save_locked_post(other)
    store.save_author(AuthorInfo('writer', LATER, title='Updated author'))

    assert store.find_post('writer', POST_ID) == LocatedPost(folder, record)
    assert _snapshot([post_file]) == before_record
    assert _snapshot(retained) == before_files
    assert JsonPostMarks(root).get_marks('writer', POST_ID) == marks
    reopened: PostStore = JsonPostStore(root)
    saved = reopened.find_post('writer', POST_ID)
    assert saved is not None
    assert saved.record is not None
    saved.record.post.title = 'Renamed lesson'
    saved.record.sync.page_template = 2
    reopened.save_post(saved.folder, saved.record)

    assert JsonPostMarks(root).get_marks('writer', POST_ID) == marks
    assert read_locked_posts(root, 'writer') == {POST_ID: locked, other.post.id: other}
    after_resave = _snapshot([post_file, *retained])
    reopened.clear_locked_post('writer', POST_ID)

    assert read_locked_posts(root, 'writer') == {other.post.id: other}
    assert _snapshot([post_file, *retained]) == after_resave
    assert _snapshot(retained) == before_files
    assert JsonPostMarks(root).get_marks('writer', POST_ID) == marks
    assert JsonPostStore(root).find_post('writer', POST_ID) == saved
    assert {path.name for path in (root / 'writer').iterdir()} == {
        '.boosty-downloader',
        Path(folder).name,
    }


def test_saved_and_loaded_nested_values_are_independent_snapshots(
    root: Path, store: PostStore, record: StoredPost
):
    expected = deepcopy(record)
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    record.post.tags.clear()
    record.post.content_counters.clear()
    record.blocks.clear()
    record.media[MEDIA_ID].path = 'files/edited.zip'
    first = store.find_post('writer', POST_ID)
    second = store.find_post('writer', POST_ID)
    assert first == second == LocatedPost(folder, expected)
    assert first is not None
    assert first.record is not None

    first.record.post.tags.append('edited')
    first.record.media[MEDIA_ID].status = MediaStatus.deleted
    text = first.record.blocks[0]
    assert isinstance(text, TextBlock)
    fragment = text.fragments[0]
    assert isinstance(fragment, PostDataChunkText.TextFragment)
    fragment.text = 'Changed in memory'
    fragment.style.bold = True

    assert second == LocatedPost(folder, expected)
    assert store.find_post('writer', POST_ID) == LocatedPost(folder, expected)
    assert JsonPostStore(root).find_post('writer', POST_ID) == LocatedPost(
        folder, expected
    )


def test_authors_with_the_same_post_id_remain_independent(
    root: Path, store: PostStore, record: StoredPost
):
    other = replace(
        record,
        post=replace(
            record.post,
            author='other',
            title='Other lesson',
            url=f'https://boosty.to/other/posts/{POST_ID}',
        ),
    )
    folders: dict[str, str] = {}
    for item in (record, other):
        folder = store.choose_post_folder(item.post)
        folders[item.post.author] = folder
        store.save_post(folder, item)
        store.save_author(AuthorInfo(item.post.author, NOW, title=item.post.title))
        store.save_locked_post(LockedPost(item.post, NOW))
    before = _snapshot(path for path in (root / 'other').rglob('*') if path.is_file())

    store.save_author(AuthorInfo('writer', LATER, title='New blog title'))
    store.clear_locked_post('writer', POST_ID)

    assert _snapshot(before) == before
    assert read_author_record(root, 'writer') == AuthorInfo(
        'writer', LATER, title='New blog title'
    )
    assert read_locked_posts(root, 'writer') == {}
    assert read_locked_posts(root, 'other') == {POST_ID: LockedPost(other.post, NOW)}
    assert store.find_post('writer', POST_ID) == LocatedPost(folders['writer'], record)
    assert store.find_post('other', POST_ID) == LocatedPost(folders['other'], other)


def test_relative_root_stays_fixed_after_working_directory_changes(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    store: PostStore = JsonPostStore(Path('library'))
    elsewhere = tmp_path / 'elsewhere'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    author = AuthorInfo('writer', NOW)
    store.save_author(author)
    store.save_locked_post(LockedPost(record.post, NOW))
    root = tmp_path / 'library'

    assert store.find_post('writer', POST_ID) == LocatedPost(folder, record)
    assert read_author_record(root, 'writer') == author
    assert POST_ID in read_locked_posts(root, 'writer')
    store.clear_locked_post('writer', POST_ID)
    assert read_locked_posts(root, 'writer') == {}
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize(
    'viewer_data',
    [None, b'{broken', b'{"schema_version": 2}'],
    ids=['absent', 'corrupt', 'unsupported'],
)
def test_content_operations_preserve_absent_or_unreadable_marks(
    root: Path, store: PostStore, record: StoredPost, viewer_data: bytes | None
) -> None:
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    viewer = root / folder / VIEWER_RECORD_FILENAME
    before: dict[Path, FileSnapshot] = {}
    if viewer_data is not None:
        viewer.write_bytes(viewer_data)
        before = _snapshot([viewer])
    updated = replace(record, post=replace(record.post, title='Edited lesson'))

    store.save_author(AuthorInfo('writer', LATER, title='New author title'))
    store.save_locked_post(LockedPost(record.post, LATER))
    store.save_post(folder, updated)
    assert store.find_post('writer', POST_ID) == LocatedPost(folder, updated)
    store.choose_post_folder(updated.post)
    store.clear_locked_post('writer', POST_ID)

    assert read_author_record(root, 'writer') == AuthorInfo(
        'writer', LATER, title='New author title'
    )
    assert read_locked_posts(root, 'writer') == {}
    if viewer_data is None:
        assert not viewer.exists()
        assert JsonPostMarks(root).get_marks('writer', POST_ID) == PostMarks()
    else:
        assert _snapshot([viewer]) == before


def test_marks_creation_and_replacement_preserve_content_metadata_and_assets(
    root: Path, store: PostStore, record: StoredPost, marks: PostMarks
) -> None:
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    _seed_retained_files(root, folder, marks)
    store.save_author(
        AuthorInfo(
            'writer',
            NOW,
            avatar_path='.boosty-downloader/avatar.jpg',
            cover_path='.boosty-downloader/cover.png',
        )
    )
    store.save_locked_post(
        LockedPost(record.post, LATER, f'.boosty-downloader/teasers/{POST_ID}.jpg')
    )
    viewer = root / folder / VIEWER_RECORD_FILENAME
    viewer.unlink()
    before = _snapshot(path for path in root.rglob('*') if path.is_file())
    mark_store = JsonPostMarks(root)

    for replacement in (marks, PostMarks()):
        mark_store.save_marks('writer', POST_ID, replacement)

        assert mark_store.get_marks('writer', POST_ID) == replacement
        assert (
            _snapshot(
                path for path in root.rglob('*') if path.is_file() and path != viewer
            )
            == before
        )


def test_post_edit_keeps_positions_for_removed_media(
    root: Path, store: PostStore, record: StoredPost, marks: PostMarks
) -> None:
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    retained = _seed_retained_files(root, folder, marks)
    before = _snapshot(retained)
    updated = replace(
        record,
        post=replace(record.post, updated_at=LATER, content_counters={'file': 1}),
        sync=replace(record.sync, synced_at=LATER),
        blocks=[
            TextBlock([PostDataChunkText.TextFragment('Updated body')]),
            MediaBlock(MEDIA_ID),
        ],
        media={
            **record.media,
            AUDIO_ID: replace(record.media[AUDIO_ID], removed_at=LATER),
        },
    )

    store.save_post(folder, updated)

    assert store.find_post('writer', POST_ID) == LocatedPost(folder, updated)
    assert JsonPostMarks(root).get_marks('writer', POST_ID) == marks
    assert _snapshot(retained) == before


def test_library_move_keeps_content_and_marks_at_the_new_root(
    tmp_path: Path, root: Path, store: PostStore, record: StoredPost, marks: PostMarks
) -> None:
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    _seed_retained_files(root, folder, marks)
    store.save_author(AuthorInfo('writer', NOW, title='Lessons'))
    before = _snapshot(path for path in root.rglob('*') if path.is_file())
    moved = root.rename(tmp_path / 'moved-library')

    assert JsonPostStore(moved).find_post('writer', POST_ID) == LocatedPost(
        folder, record
    )
    assert JsonPostMarks(moved).get_marks('writer', POST_ID) == marks
    expected = {
        moved / path.relative_to(root): snapshot for path, snapshot in before.items()
    }
    assert _snapshot(path for path in moved.rglob('*') if path.is_file()) == expected


def test_deleted_post_saved_again_starts_without_marks(
    root: Path, store: PostStore, record: StoredPost, marks: PostMarks
) -> None:
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    _seed_retained_files(root, folder, marks)
    mark_store = JsonPostMarks(root)
    rmtree(root / folder)
    assert mark_store.get_marks('writer', POST_ID) is None

    new_run = JsonPostStore(root)
    new_folder = new_run.choose_post_folder(record.post)
    new_run.save_post(new_folder, record)

    assert new_folder == folder
    assert new_run.find_post('writer', POST_ID) == LocatedPost(new_folder, record)
    assert mark_store.get_marks('writer', POST_ID) == PostMarks()
    assert not (root / new_folder / VIEWER_RECORD_FILENAME).exists()
