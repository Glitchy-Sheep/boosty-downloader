"""Unrecorded files recover local state without changing content or media history."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from boosty_downloader.application.mappers.live_post import LiveMedia
from boosty_downloader.application.media_paths import DiskSnapshot
from boosty_downloader.application.reconcile import recover_media_files
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
OTHER_ID = 'file:other'
SAVED_PATH = 'files/saved.zip'
PREFERRED_PATH = 'files/lesson.zip'
RECOVERABLE_STATUSES = [
    MediaStatus.pending,
    MediaStatus.failed,
    MediaStatus.unavailable,
]


def _record(status: MediaStatus, *, path: str | None = SAVED_PATH) -> StoredPost:
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
                path=path,
                size=12,
                filename='lesson.zip',
                preview_path='images/preview.jpg',
                error='previous result',
            )
        },
    )


def _live(*, expected_size: int | None = 40) -> dict[str, LiveMedia]:
    return {
        MEDIA_ID: LiveMedia(
            kind=MediaKind.file,
            download=None,
            expected_size=expected_size,
            filename='lesson.zip',
        )
    }


@pytest.mark.parametrize('status', RECOVERABLE_STATUSES)
@pytest.mark.parametrize('expected_size', [None, 40])
def test_saved_path_wins_over_preferred_even_for_an_unfinished_upload(
    status: MediaStatus, expected_size: int | None
):
    record = _record(status)
    disk = DiskSnapshot({SAVED_PATH: 40, PREFERRED_PATH: 40})

    result = recover_media_files(record, _live(expected_size=expected_size), disk)

    recovered = replace(
        record.media[MEDIA_ID], status=MediaStatus.downloaded, size=40, error=None
    )
    assert result == replace(record, media={MEDIA_ID: recovered})


@pytest.mark.parametrize('status', RECOVERABLE_STATUSES)
@pytest.mark.parametrize('saved_size', [None, 0, 12], ids=['absent', 'empty', 'short'])
def test_a_missing_or_implausible_saved_file_falls_back_to_the_preferred_name(
    status: MediaStatus, saved_size: int | None
):
    record = _record(status)
    files = {PREFERRED_PATH: 40}
    if saved_size is not None:
        files[SAVED_PATH] = saved_size

    result = recover_media_files(record, _live(), DiskSnapshot(files))

    recovered = replace(
        record.media[MEDIA_ID],
        status=MediaStatus.downloaded,
        path=PREFERRED_PATH,
        size=40,
        error=None,
    )
    assert result == replace(record, media={MEDIA_ID: recovered})


@pytest.mark.parametrize('status', RECOVERABLE_STATUSES)
@pytest.mark.parametrize('observed_size', [None, 0, 12])
def test_no_plausible_file_preserves_the_whole_previous_result(
    status: MediaStatus, observed_size: int | None
):
    record = _record(status)
    files = {}
    if observed_size is not None:
        files = {SAVED_PATH: observed_size, PREFERRED_PATH: observed_size}

    assert recover_media_files(record, _live(), DiskSnapshot(files)) == record


@pytest.mark.parametrize('status', RECOVERABLE_STATUSES)
def test_removed_media_recovers_recorded_bytes_without_using_stale_stored_size(
    status: MediaStatus,
):
    record = _record(status)
    record.media[MEDIA_ID].removed_at = REMOVED
    record.blocks.clear()

    result = recover_media_files(record, {}, DiskSnapshot({SAVED_PATH: 40}))

    recovered = replace(
        record.media[MEDIA_ID], status=MediaStatus.downloaded, size=40, error=None
    )
    assert result == replace(record, media={MEDIA_ID: recovered})


@pytest.mark.parametrize('status', RECOVERABLE_STATUSES)
def test_removed_media_does_not_guess_from_a_stored_filename_or_accept_empty_bytes(
    status: MediaStatus,
):
    record = _record(status)
    record.media[MEDIA_ID].removed_at = REMOVED
    record.blocks.clear()
    disk = DiskSnapshot({SAVED_PATH: 0, PREFERRED_PATH: 40})

    assert recover_media_files(record, {}, disk) == record


@pytest.mark.parametrize('owner_status', list(MediaStatus))
@pytest.mark.parametrize('removed_at', [None, REMOVED], ids=['current', 'removed'])
def test_a_later_owners_retained_path_blocks_discovery_through_an_alias(
    owner_status: MediaStatus, removed_at: datetime | None
):
    record = _record(MediaStatus.pending, path=None)
    owner = replace(
        record.media[MEDIA_ID],
        status=owner_status,
        position=1,
        path='files/old-spelling.zip',
        removed_at=removed_at,
    )
    record.media[OTHER_ID] = owner
    disk = DiskSnapshot(
        {PREFERRED_PATH: 40}, aliases={'files/old-spelling.zip': PREFERRED_PATH}
    )

    result = recover_media_files(record, _live(), disk)

    assert result.media[MEDIA_ID] == record.media[MEDIA_ID]


def test_a_missing_removed_copy_still_reserves_its_portable_path():
    record = _record(MediaStatus.pending, path=None)
    record.media[OTHER_ID] = replace(
        record.media[MEDIA_ID],
        status=MediaStatus.deleted,
        position=1,
        removed_at=REMOVED,
        path='files/LESSON.zip',
    )
    disk = DiskSnapshot({PREFERRED_PATH: 40})

    assert recover_media_files(record, _live(), disk) == record


@pytest.mark.parametrize('use_alias', [False, True], ids=['exact', 'alias'])
def test_competing_pieces_claim_a_file_once_in_position_order(*, use_alias: bool):
    record = _record(MediaStatus.pending, path=None)
    first = record.media[MEDIA_ID]
    second = replace(first, position=1)
    record.media = {OTHER_ID: second, MEDIA_ID: first}
    live = _live()
    live[OTHER_ID] = deepcopy(live[MEDIA_ID])
    aliases = {}
    if use_alias:
        live[MEDIA_ID].filename = 'LESSON.zip'
        aliases = {'files/LESSON.zip': PREFERRED_PATH}
    disk = DiskSnapshot({PREFERRED_PATH: 40}, aliases=aliases)

    result = recover_media_files(record, live, disk)

    assert result.media[MEDIA_ID] == replace(
        first,
        status=MediaStatus.downloaded,
        path=PREFERRED_PATH,
        size=40,
        error=None,
    )
    assert result.media[OTHER_ID] == second


@pytest.mark.parametrize('status', [MediaStatus.downloaded, MediaStatus.deleted])
@pytest.mark.parametrize('observed_size', [None, 0, 40])
def test_owned_states_are_left_for_recorded_file_observation(
    status: MediaStatus, observed_size: int | None
):
    record = _record(status)
    files = {PREFERRED_PATH: 40}
    if observed_size is not None:
        files[SAVED_PATH] = observed_size

    assert recover_media_files(record, _live(), DiskSnapshot(files)) == record


@pytest.mark.parametrize('path', [None, 'external_videos/lesson.mp4'])
def test_external_media_only_recovers_a_recorded_path(path: str | None):
    record = _record(MediaStatus.failed, path=path)
    external_id = f'{MediaKind.external_video.value}:https://example.org/watch'
    entry = replace(record.media[MEDIA_ID], kind=MediaKind.external_video)
    record.media = {external_id: entry}
    record.blocks = [MediaBlock(external_id)]
    live = {
        external_id: LiveMedia(
            kind=MediaKind.external_video, download=None, title='lesson'
        )
    }
    disk = DiskSnapshot({'external_videos/lesson.mp4': 40})

    result = recover_media_files(record, live, disk)

    expected = entry
    if path is not None:
        expected = replace(entry, status=MediaStatus.downloaded, size=40, error=None)
    assert result == replace(record, media={external_id: expected})


def test_recovery_owns_the_result_and_preserves_all_inputs():
    record = _record(MediaStatus.failed)
    record.media[OTHER_ID] = replace(record.media[MEDIA_ID], position=1, path=None)
    fragment = PostDataChunkText.TextFragment('Saved text')
    fragment.style.bold = True
    record.blocks.append(TextBlock([fragment]))
    live = _live()
    disk = DiskSnapshot(
        {SAVED_PATH: 40}, occupied={'files/unrelated'}, aliases={'saved': SAVED_PATH}
    )
    original_record, original_live, original_disk = deepcopy((record, live, disk))

    result = recover_media_files(record, live, disk)

    text = result.blocks[-1]
    assert isinstance(text, TextBlock)
    copied_fragment = text.fragments[0]
    assert isinstance(copied_fragment, PostDataChunkText.TextFragment)
    copied_fragment.style.bold = False
    result.post.tags.append('local edit')
    result.post.content_counters['file'] = 99
    result.media[MEDIA_ID].path = 'files/local-edit.zip'
    result.media[OTHER_ID].error = 'unrecovered entry edit'
    result.sync.page_template = 99
    assert record == original_record
    assert live == original_live
    assert disk == original_disk
