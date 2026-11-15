"""Saved locked-post reads preserve ownership and independent values."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from support.memory_post_store import MemoryPostStore

from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.stored_post import (
    LockedPost,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_SERVICE_FOLDER,
    LOCKED_RECORD_FILENAME,
)
from boosty_downloader.infrastructure.library.db_post_store import DatabasePostStore
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase
from boosty_downloader.infrastructure.library.errors import InvalidAuthorRecordError
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from boosty_downloader.application.ports import PostStore

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


@pytest.fixture(params=['memory', 'json', 'database'])
def store(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Generator[PostStore, None, None]:
    if request.param == 'memory':
        yield MemoryPostStore()
    elif request.param == 'json':
        yield JsonPostStore(tmp_path / 'library')
    else:
        with LibraryDatabase.create(tmp_path / 'library.db') as database:
            yield DatabasePostStore(tmp_path / 'library', database)


@pytest.fixture
def locked() -> LockedPost:
    return LockedPost(
        post=PostMetadata(
            'lesson',
            'writer',
            'https://boosty.to/writer/posts/lesson',
            'Lesson',
            NOW,
            NOW,
            tags=['course'],
            content_counters={'image': 2},
            tier='Lessons',
        ),
        synced_at=NOW,
        teaser_path=f'{AUTHOR_SERVICE_FOLDER}/teasers/lesson.jpg',
    )


def test_absent_observation_read_creates_no_library(
    store: PostStore, tmp_path: Path
) -> None:
    assert store.load_locked_post('writer', 'lesson') is None
    assert not (tmp_path / 'library').exists()


def test_locked_reads_own_their_nested_values(
    store: PostStore, locked: LockedPost
) -> None:
    expected = deepcopy(locked)
    store.save_locked_post(locked)
    locked.post.tags.append('Changed input')
    first = store.load_locked_post('writer', 'lesson')
    second = store.load_locked_post('writer', 'lesson')
    assert first == second == expected
    assert first is not None
    first.post.tags.append('Changed result')
    first.post.content_counters['image'] = 10
    first.teaser_path = None
    assert second == expected
    assert store.load_locked_post('writer', 'lesson') == expected
    store.save_locked_post(first)
    assert store.load_locked_post('writer', 'lesson') == first


def test_author_and_full_post_id_select_independent_observations(
    store: PostStore,
    locked: LockedPost,
) -> None:
    other_author = deepcopy(locked)
    other_author.post.author = 'another'
    other_post = deepcopy(locked)
    other_post.post.id = 'other-lesson'
    store.save_locked_post(locked)
    store.save_locked_post(other_author)
    store.save_locked_post(other_post)
    store.clear_locked_post('writer', 'lesson')
    assert store.load_locked_post('writer', 'lesson') is None
    assert store.load_locked_post('another', 'lesson') == other_author
    assert store.load_locked_post('writer', 'other-lesson') == other_post
    assert store.load_locked_post('unknown', 'lesson') is None
    assert store.load_locked_post('writer', 'unknown') is None


def test_saved_body_updates_do_not_establish_restored_access(
    store: PostStore,
    locked: LockedPost,
) -> None:
    saved = StoredPost(
        replace(locked.post, title='Saved overview', tags=['saved']), PostSync(NOW, NOW)
    )
    folder = store.choose_post_folder(saved.post)
    store.save_post(folder, saved)
    store.save_locked_post(locked)
    saved.post.title = 'Offline update'
    saved.post.tags = ['offline']
    store.save_post(folder, saved)
    assert store.load_locked_post('writer', 'lesson') == locked
    assert store.find_post('writer', 'lesson') == LocatedPost(folder, saved)
    store.clear_locked_post('writer', 'lesson')
    assert store.load_locked_post('writer', 'lesson') is None
    assert store.find_post('writer', 'lesson') == LocatedPost(folder, saved)


@pytest.mark.parametrize('clear_first', [False, True])
def test_locked_only_observation_becomes_accessible_in_either_save_order(
    store: PostStore,
    locked: LockedPost,
    *,
    clear_first: bool,
) -> None:
    store.save_locked_post(locked)
    saved = StoredPost(replace(locked.post, title='Now accessible'), PostSync(NOW, NOW))
    folder = store.choose_post_folder(saved.post)
    if clear_first:
        store.clear_locked_post('writer', 'lesson')
    store.save_post(folder, saved)
    if not clear_first:
        assert store.load_locked_post('writer', 'lesson') == locked
        store.clear_locked_post('writer', 'lesson')
    assert store.load_locked_post('writer', 'lesson') is None
    assert store.find_post('writer', 'lesson') == LocatedPost(folder, saved)


def test_absent_clear_does_not_create_a_library(
    store: PostStore, tmp_path: Path
) -> None:
    store.clear_locked_post('writer', 'lesson')
    assert not (tmp_path / 'library').exists()


@pytest.mark.parametrize(
    'data',
    [
        b'{broken',
        b'{"schema_version": 999}',
        b'{"schema_version": 1}',
        b'{"schema_version": 1, "author": "other", "posts": {}}',
    ],
    ids=['invalid-json', 'future-schema', 'missing-fields', 'wrong-owner'],
)
def test_invalid_locked_document_is_not_read_as_an_absent_post(
    tmp_path: Path,
    data: bytes,
) -> None:
    path = tmp_path / 'writer' / AUTHOR_SERVICE_FOLDER / LOCKED_RECORD_FILENAME
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    original_mtime = path.stat().st_mtime_ns
    store: PostStore = JsonPostStore(tmp_path)
    with pytest.raises(InvalidAuthorRecordError):
        store.load_locked_post('writer', 'lesson')
    assert path.read_bytes() == data
    assert path.stat().st_mtime_ns == original_mtime
