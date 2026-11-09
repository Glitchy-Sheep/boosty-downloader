"""Author reads preserve snapshots consistently across PostStore adapters."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from support.memory_post_store import MemoryPostStore

from boosty_downloader.domain.stored_post import AuthorInfo
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_RECORD_FILENAME,
    AUTHOR_SERVICE_FOLDER,
)
from boosty_downloader.infrastructure.library.errors import InvalidAuthorRecordError
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import PostStore

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)


@pytest.fixture(params=['memory', 'json'])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> PostStore:
    if request.param == 'memory':
        return MemoryPostStore()
    return JsonPostStore(tmp_path / 'library')


@pytest.fixture
def author() -> AuthorInfo:
    return AuthorInfo(
        'writer',
        NOW,
        title='Lessons',
        owner_name='Fixture writer',
        description='First paragraph\n\nSecond paragraph',
        avatar_path=f'{AUTHOR_SERVICE_FOLDER}/avatar.jpg',
        cover_path=f'{AUTHOR_SERVICE_FOLDER}/cover.png',
        remote_post_count=0,
    )


def test_missing_author_reads_do_not_create_a_library(
    store: PostStore, tmp_path: Path
) -> None:
    assert store.load_author('writer') is None
    assert not (tmp_path / 'library').exists()


def test_author_reads_preserve_all_fields_and_own_their_values(
    store: PostStore, author: AuthorInfo
) -> None:
    expected = deepcopy(author)
    store.save_author(author)
    author.title = 'Changed input'
    first = store.load_author('writer')
    second = store.load_author('writer')
    assert first == second == expected
    assert first is not None

    first.title = 'Changed read'
    first.avatar_path = None

    assert second == expected
    assert store.load_author('writer') == expected
    store.save_author(first)
    assert store.load_author('writer') == first


def test_reading_and_updating_one_author_preserves_others(
    store: PostStore, author: AuthorInfo
) -> None:
    other = AuthorInfo('another', NOW, title='Other blog')
    store.save_author(author)
    store.save_author(other)
    author.title = 'Edited blog'
    store.save_author(author)

    assert store.load_author('writer') == author
    assert store.load_author('another') == other
    assert store.load_author('unknown') is None


@pytest.mark.parametrize(
    'data',
    [b'{broken', b'{"schema_version": 999}', b'{"schema_version": 1}'],
    ids=['invalid-json', 'future-schema', 'missing-fields'],
)
def test_json_author_read_reports_unreadable_records_without_changing_them(
    tmp_path: Path, data: bytes
) -> None:
    path = tmp_path / 'writer' / AUTHOR_SERVICE_FOLDER / AUTHOR_RECORD_FILENAME
    path.parent.mkdir(parents=True)
    path.write_bytes(data)
    before = path.stat().st_mtime_ns
    store: PostStore = JsonPostStore(tmp_path)

    with pytest.raises(InvalidAuthorRecordError):
        store.load_author('writer')

    assert path.read_bytes() == data
    assert path.stat().st_mtime_ns == before
