"""Recorded-file observations preserve content and media history."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from boosty_downloader.application.media_paths import DiskSnapshot
from boosty_downloader.application.reconcile import observe_recorded_files
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)

FIRST = datetime(2026, 1, 1, tzinfo=timezone.utc)
REMOVED = FIRST + timedelta(days=1)
MEDIA_ID = 'file:fixture'
SAVED_PATH = 'files/saved.zip'


def _record(
    status: MediaStatus,
    *,
    removed_at: datetime | None = None,
    path: str | None = SAVED_PATH,
) -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            id='fixture',
            author='fixture',
            url='https://boosty.to/fixture/posts/fixture',
            title='Lesson',
            created_at=FIRST,
            updated_at=FIRST,
            tags=['lesson'],
        ),
        sync=PostSync(FIRST, FIRST, page_template=4),
        blocks=[MediaBlock(MEDIA_ID)],
        media={
            MEDIA_ID: MediaEntry(
                kind=MediaKind.file,
                status=status,
                added_at=FIRST,
                position=0,
                removed_at=removed_at,
                path=path,
                size=12,
                filename='new-name.zip',
                preview_path='images/preview.jpg',
                error='previous result',
            )
        },
    )


@pytest.mark.parametrize('status', [MediaStatus.downloaded, MediaStatus.deleted])
@pytest.mark.parametrize('removed_at', [None, REMOVED], ids=['current', 'removed'])
@pytest.mark.parametrize(
    'actual_size', [0, 40], ids=['emptied-by-user', 'changed-size']
)
def test_observed_file_keeps_actual_bytes_and_history(
    status: MediaStatus,
    removed_at: datetime | None,
    actual_size: int,
):
    record = _record(status, removed_at=removed_at)

    result = observe_recorded_files(record, DiskSnapshot({SAVED_PATH: actual_size}))

    expected_entry = replace(
        record.media[MEDIA_ID],
        status=MediaStatus.downloaded,
        size=actual_size,
        error=None,
    )
    assert result == replace(record, media={MEDIA_ID: expected_entry})


@pytest.mark.parametrize('status', [MediaStatus.downloaded, MediaStatus.deleted])
@pytest.mark.parametrize('removed_at', [None, REMOVED], ids=['current', 'removed'])
@pytest.mark.parametrize('path', [SAVED_PATH, None], ids=['saved-path', 'unknown-path'])
def test_missing_file_becomes_deleted_without_adopting_a_preferred_lookalike(
    status: MediaStatus,
    removed_at: datetime | None,
    path: str | None,
):
    record = _record(status, removed_at=removed_at, path=path)
    disk = DiskSnapshot({'files/new-name.zip': 12})

    result = observe_recorded_files(record, disk)

    expected_entry = replace(record.media[MEDIA_ID], status=MediaStatus.deleted)
    assert result == replace(record, media={MEDIA_ID: expected_entry})


def test_only_a_confirmed_alias_restores_a_differently_spelled_path():
    record = _record(MediaStatus.deleted)
    actual = 'files/SAVED.zip'
    files = {actual: 21}
    assert observe_recorded_files(record, DiskSnapshot(files)) == record

    result = observe_recorded_files(
        record, DiskSnapshot(files, aliases={SAVED_PATH: actual})
    )

    expected_entry = replace(
        record.media[MEDIA_ID],
        status=MediaStatus.downloaded,
        path=actual,
        size=21,
        error=None,
    )
    assert result == replace(record, media={MEDIA_ID: expected_entry})


@pytest.mark.parametrize('path', ['files/.download.part', SAVED_PATH])
def test_a_hidden_partial_file_is_absent_even_through_a_confirmed_alias(path: str):
    record = _record(MediaStatus.downloaded, path=path)
    disk = DiskSnapshot(
        {'files/.download.part': 12}, aliases={SAVED_PATH: 'files/.download.part'}
    )

    result = observe_recorded_files(record, disk)

    expected_entry = replace(record.media[MEDIA_ID], status=MediaStatus.deleted)
    assert result == replace(record, media={MEDIA_ID: expected_entry})


@pytest.mark.parametrize(
    'status',
    [
        MediaStatus.pending,
        MediaStatus.failed,
        MediaStatus.unavailable,
    ],
)
@pytest.mark.parametrize('removed_at', [None, REMOVED], ids=['current', 'removed'])
def test_other_states_wait_for_discovery_even_when_the_reserved_file_exists(
    status: MediaStatus,
    removed_at: datetime | None,
):
    record = _record(status, removed_at=removed_at)

    assert observe_recorded_files(record, DiskSnapshot({SAVED_PATH: 12})) == record


def test_observation_returns_owned_content_without_mutating_record_or_snapshot():
    record = _record(MediaStatus.downloaded)
    fragment = PostDataChunkText.TextFragment('Saved text')
    fragment.style.bold = True
    record.blocks.append(TextBlock([fragment]))
    disk = DiskSnapshot(
        {SAVED_PATH: 0},
        occupied={'files/unrelated'},
        aliases={'files/SAVED.zip': SAVED_PATH},
    )
    original_record = deepcopy(record)
    original_disk = deepcopy(disk)

    result = observe_recorded_files(record, disk)

    text = result.blocks[-1]
    assert isinstance(text, TextBlock)
    copied_fragment = text.fragments[0]
    assert isinstance(copied_fragment, PostDataChunkText.TextFragment)
    copied_fragment.style.bold = False
    result.post.tags.append('local edit')
    result.media[MEDIA_ID].path = 'files/local-edit.zip'
    result.sync.page_template = 99
    assert record == original_record
    assert disk == original_disk
