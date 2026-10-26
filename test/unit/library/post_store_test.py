"""The JSON PostStore preserves saved content across changes in live access."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.domain.library import LocatedPost
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
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from collections.abc import Iterable

    from boosty_downloader.application.ports import PostStore

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=7)
POST_ID = 'abcdefgh-first'
MEDIA_ID = 'file:lesson'
MEDIA_BYTES = b'Saved lesson file'


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
            content_counters={'file': 1},
        ),
        sync=PostSync(NOW, NOW, page_template=1),
        blocks=[
            TextBlock([PostDataChunkText.TextFragment('Saved body')]),
            MediaBlock(MEDIA_ID),
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
        },
    )


def _snapshot(paths: Iterable[Path]) -> dict[Path, FileSnapshot]:
    return {
        path: FileSnapshot(path.read_bytes(), path.stat().st_mtime_ns) for path in paths
    }


def _seed_retained_files(root: Path, folder: str) -> list[Path]:
    files = {
        root / folder / 'files/lesson.zip': MEDIA_BYTES,
        root / folder / 'post.html': b'<p>Saved page</p>',
        root / folder / 'viewer.json': b'{"favorite": true}',
        root / 'writer/.boosty-downloader/avatar.jpg': b'avatar',
        root / 'writer/.boosty-downloader/cover.png': b'cover',
        root / f'writer/.boosty-downloader/teasers/{POST_ID}.jpg': b'teaser',
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return list(files)


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
    root: Path, store: PostStore, record: StoredPost
):
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    retained = _seed_retained_files(root, folder)
    before_files = _snapshot(retained)
    post_file = root / folder / 'post.json'
    before_record = _snapshot([post_file])
    locked = LockedPost(record.post, LATER)
    other = LockedPost(replace(record.post, id='abcdefgh-second'), LATER)

    store.save_locked_post(locked)
    store.save_locked_post(other)

    assert store.find_post('writer', POST_ID) == LocatedPost(folder, record)
    assert _snapshot([post_file]) == before_record
    assert _snapshot(retained) == before_files
    reopened: PostStore = JsonPostStore(root)
    saved = reopened.find_post('writer', POST_ID)
    assert saved is not None
    assert saved.record is not None
    saved.record.post.title = 'Renamed lesson'
    saved.record.sync.page_template = 2
    reopened.save_post(saved.folder, saved.record)

    assert read_locked_posts(root, 'writer') == {POST_ID: locked, other.post.id: other}
    after_resave = _snapshot([post_file, *retained])
    reopened.clear_locked_post('writer', POST_ID)

    assert read_locked_posts(root, 'writer') == {other.post.id: other}
    assert _snapshot([post_file, *retained]) == after_resave
    assert _snapshot(retained) == before_files
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
