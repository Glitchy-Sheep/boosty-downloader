"""The complete primary PostStore facade keeps independent state across reopen."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LockedPost,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library.db_post_store import DatabasePostStore
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import PostStore

NOW = datetime(2026, 11, 15, 12, 34, 56, 123456, tzinfo=timezone.utc)


def test_facade_reopens_independent_author_saved_and_access_snapshots(tmp_path: Path):
    root = tmp_path / 'library'
    path = tmp_path / 'library.db'
    author = AuthorInfo('writer', NOW, title='Known blog')
    metadata = PostMetadata(
        'abcdefgh-first',
        'writer',
        'https://boosty.to/example',
        'Saved title',
        NOW,
        NOW,
        tags=['saved'],
    )
    saved = StoredPost(metadata, PostSync(NOW, NOW))
    locked = LockedPost(replace(metadata, title='Locked title', tags=['locked']), NOW)
    with LibraryDatabase.create(path) as database:
        store: PostStore = DatabasePostStore(root, database)
        store.save_author(author)
        folder = store.choose_post_folder(saved.post)
        store.save_post(folder, saved)
        store.save_locked_post(locked)
        saved.post.title = 'Offline title'
        store.save_post(folder, saved)
    with LibraryDatabase.open(path) as database:
        reader: PostStore = DatabasePostStore(root, database)
        assert reader.load_author('writer') == author
        assert reader.load_locked_post('writer', metadata.id) == locked
        assert reader.find_post('writer', metadata.id) == LocatedPost(folder, saved)
    with LibraryDatabase.open(path, writable=True) as database:
        writer: PostStore = DatabasePostStore(root, database)
        writer.clear_locked_post('writer', metadata.id)
    with LibraryDatabase.open(path) as database:
        reader = DatabasePostStore(root, database)
        assert reader.load_locked_post('writer', metadata.id) is None
        assert reader.find_post('writer', metadata.id) == LocatedPost(folder, saved)
        assert reader.load_author('writer') == author


def test_locked_snapshot_normalizes_every_clock_without_mutating_input(tmp_path: Path):
    local_time = NOW.astimezone(timezone(timedelta(hours=3)))
    locked = LockedPost(
        PostMetadata(
            'abcdefgh-first',
            'writer',
            'https://boosty.to/example',
            'Locked title',
            local_time,
            local_time,
            published_at=local_time,
            tags=['locked'],
            content_counters={'video': 2},
        ),
        local_time,
    )
    expected = deepcopy(locked)
    with LibraryDatabase.create(tmp_path / 'library.db') as database:
        store: PostStore = DatabasePostStore(tmp_path / 'library', database)
        store.save_locked_post(locked)
        loaded = store.load_locked_post('writer', locked.post.id)
        assert loaded == expected
        assert loaded is not None
        assert loaded.post.published_at is not None
        assert loaded.synced_at.tzinfo is timezone.utc
        assert loaded.post.created_at.tzinfo is timezone.utc
        assert loaded.post.updated_at.tzinfo is timezone.utc
        assert loaded.post.published_at.tzinfo is timezone.utc
        loaded.post.tags.append('Caller mutation')
        loaded.post.content_counters.clear()
        assert store.load_locked_post('writer', locked.post.id) == expected
    assert locked == expected
