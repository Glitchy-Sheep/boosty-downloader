"""Public reconciliation plans downloads while retaining complete post history."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from boosty_downloader.application.mappers.live_post import LiveMedia, LivePost
from boosty_downloader.application.media_paths import DiskSnapshot
from boosty_downloader.application.reconcile import reconcile
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
    PostDataChunkText,
)
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
NOW = FIRST + timedelta(days=7)
LATER = NOW + timedelta(days=1)
ALL_FILTERS = list(DownloadContentTypeFilter)
FILE_ID = 'file:fixture'
IMAGE_ID = 'image:fixture'
SAVED_PATH = 'saved/file'


def _media_id(kind: MediaKind) -> str:
    if kind is MediaKind.external_video:
        return f'{kind.value}:https://example.org/watch'
    return f'{kind.value}:fixture'


def _ready_media(kind: MediaKind) -> LiveMedia:
    url = 'https://cdn.example/lesson'
    match kind:
        case MediaKind.image:
            download = PostDataChunkImage(id='fixture', url=url)
        case MediaKind.file:
            download = PostDataChunkFile(id='fixture', url=url, filename='lesson.zip')
        case MediaKind.audio:
            download = PostDataChunkAudio(id='fixture', url=url, title='lesson.mp3')
        case MediaKind.boosty_video:
            download = PostDataChunkBoostyVideo(
                id='fixture', title='Lesson', url=url, quality='high'
            )
        case MediaKind.external_video:
            download = PostDataChunkExternalVideo(url='https://example.org/watch')
    return LiveMedia(kind=kind, download=download, filename='lesson.zip')


def _live(*kinds: MediaKind) -> LivePost:
    return LivePost(
        post=PostMetadata(
            id='fixture',
            author='fixture',
            url='https://boosty.to/fixture/posts/fixture',
            title='Lesson',
            created_at=FIRST,
            updated_at=FIRST,
            tags=['lesson'],
        ),
        has_access=True,
        blocks=[
            TextBlock([PostDataChunkText.TextFragment('Complete lesson')]),
            *(MediaBlock(_media_id(kind)) for kind in kinds),
        ],
        media={_media_id(kind): _ready_media(kind) for kind in kinds},
    )


def _stored(live: LivePost, status: MediaStatus) -> StoredPost:
    return StoredPost(
        post=deepcopy(live.post),
        sync=PostSync(FIRST, FIRST, page_template=4),
        blocks=deepcopy(live.blocks),
        media={
            media_id: MediaEntry(
                kind=media.kind,
                status=status,
                added_at=FIRST,
                position=position,
                path=f'saved/{media.kind.value}',
                size=12,
                filename=media.filename,
                error='previous result',
            )
            for position, (media_id, media) in enumerate(live.media.items())
        },
    )


@pytest.mark.parametrize(
    ('selected', 'kind'),
    [
        (DownloadContentTypeFilter.post_content, MediaKind.image),
        (DownloadContentTypeFilter.files, MediaKind.file),
        (DownloadContentTypeFilter.audio, MediaKind.audio),
        (DownloadContentTypeFilter.boosty_videos, MediaKind.boosty_video),
        (DownloadContentTypeFilter.external_videos, MediaKind.external_video),
    ],
)
def test_each_filter_selects_its_kind_without_filtering_the_saved_body(
    selected: DownloadContentTypeFilter, kind: MediaKind
):
    live = _live(*MediaKind)

    result = reconcile(None, live, DiskSnapshot({}), [selected], NOW)

    assert result.download_ids == [_media_id(kind)]
    assert result.record is not None
    assert result.record.post == live.post
    assert result.record.blocks == live.blocks
    assert set(result.record.media) == set(live.media)
    assert result.record.sync == PostSync(NOW, NOW)
    assert all(
        entry.status is MediaStatus.pending for entry in result.record.media.values()
    )


def test_empty_filters_keep_a_complete_record_without_downloads():
    live = _live(*MediaKind)

    result = reconcile(None, live, DiskSnapshot({}), [], NOW)

    assert result.download_ids == []
    assert result.record is not None
    assert result.record.blocks == live.blocks
    assert set(result.record.media) == set(live.media)


@pytest.mark.parametrize('status', [MediaStatus.pending, MediaStatus.failed])
@pytest.mark.parametrize('ready', [False, True], ids=['unfinished', 'ready'])
@pytest.mark.parametrize('selected', [False, True], ids=['excluded', 'selected'])
def test_pending_and_failed_media_require_selection_and_readiness(
    status: MediaStatus, *, ready: bool, selected: bool
):
    live = _live(MediaKind.file)
    stored = _stored(live, status)
    if not ready:
        live.media[FILE_ID].download = None
    filters = [DownloadContentTypeFilter.files] if selected else []

    result = reconcile(stored, live, DiskSnapshot({}), filters, NOW)

    assert result.download_ids == ([FILE_ID] if ready and selected else [])
    assert result.record is not None
    assert result.record.media[FILE_ID] == stored.media[FILE_ID]


@pytest.mark.parametrize('ready', [False, True], ids=['unfinished', 'ready'])
@pytest.mark.parametrize('selected', [False, True], ids=['excluded', 'selected'])
def test_restore_changes_only_selected_deleted_media_before_readiness_is_checked(
    *, ready: bool, selected: bool
):
    live = _live(MediaKind.file)
    stored = _stored(live, MediaStatus.deleted)
    if not ready:
        live.media[FILE_ID].download = None
    filters = [DownloadContentTypeFilter.files] if selected else []

    result = reconcile(
        stored, live, DiskSnapshot({}), filters, NOW, restore_missing=True
    )

    assert result.download_ids == ([FILE_ID] if selected and ready else [])
    assert result.record is not None
    expected = stored.media[FILE_ID]
    if selected:
        expected = replace(expected, status=MediaStatus.pending)
    assert result.record.media[FILE_ID] == expected


@pytest.mark.parametrize('kind', list(MediaKind))
def test_restore_uses_the_media_kind_even_without_a_ready_download(kind: MediaKind):
    live = _live(kind)
    stored = _stored(live, MediaStatus.deleted)
    live.media[_media_id(kind)].download = None

    result = reconcile(
        stored, live, DiskSnapshot({}), ALL_FILTERS, NOW, restore_missing=True
    )

    assert result.download_ids == []
    assert result.record is not None
    assert result.record.media[_media_id(kind)].status is MediaStatus.pending


def test_unavailable_media_is_checked_once_per_run_without_losing_the_last_result():
    live = _live(MediaKind.file)
    stored = _stored(live, MediaStatus.unavailable)
    stored.sync.synced_at = NOW
    first = reconcile(stored, live, DiskSnapshot({}), ALL_FILTERS, NOW)
    checked = {FILE_ID}

    repeated = reconcile(
        first.record,
        live,
        DiskSnapshot({}),
        ALL_FILTERS,
        LATER,
        checked_unavailable_ids=checked,
    )
    next_run = reconcile(repeated.record, live, DiskSnapshot({}), ALL_FILTERS, LATER)

    assert first.download_ids == [FILE_ID]
    assert repeated.download_ids == []
    assert next_run.download_ids == [FILE_ID]
    assert checked == {FILE_ID}
    for result in [first, repeated, next_run]:
        assert result.record is not None
        assert result.record.media[FILE_ID] == stored.media[FILE_ID]


def test_a_finished_upload_is_scheduled_without_an_api_update_timestamp_change():
    live = _live(MediaKind.file)
    ready = deepcopy(live)
    live.media[FILE_ID].download = None
    unfinished = reconcile(None, live, DiskSnapshot({}), ALL_FILTERS, NOW)

    finished = reconcile(unfinished.record, ready, DiskSnapshot({}), ALL_FILTERS, LATER)

    assert unfinished.download_ids == []
    assert finished.download_ids == [FILE_ID]
    assert finished.record is not None
    assert finished.record.post.updated_at == FIRST
    assert finished.record.media[FILE_ID].added_at == NOW


@pytest.mark.parametrize('ready', [False, True])
def test_unavailable_media_still_requires_a_selected_ready_download(*, ready: bool):
    live = _live(MediaKind.file)
    stored = _stored(live, MediaStatus.unavailable)
    filters = []
    if not ready:
        live.media[FILE_ID].download = None
        filters = ALL_FILTERS

    result = reconcile(stored, live, DiskSnapshot({}), filters, NOW)

    assert result.download_ids == []
    assert result.record is not None
    assert result.record.media[FILE_ID] == stored.media[FILE_ID]


@pytest.mark.parametrize('existing', [False, True], ids=['new-locked', 'lost-access'])
def test_locked_posts_bypass_disk_and_restore_without_changing_history(
    *, existing: bool
):
    live = _live(MediaKind.file)
    stored = _stored(live, MediaStatus.downloaded) if existing else None
    original = deepcopy(stored)
    live.has_access = False
    live.post.title = 'Locked replacement'

    result = reconcile(
        stored, live, DiskSnapshot({}), ALL_FILTERS, NOW, restore_missing=True
    )

    assert result.download_ids == []
    assert result.record == original
    if result.record is not None:
        assert result.record is not stored
        result.record.post.tags.append('local edit')
        result.record.media[FILE_ID].path = 'edited'
        result.record.sync.page_template = 99
    assert stored == original


def test_a_later_full_run_keeps_the_page_and_downloads_the_remaining_kinds():
    live = _live(*MediaKind)
    first = reconcile(
        None, live, DiskSnapshot({}), [DownloadContentTypeFilter.post_content], FIRST
    )
    assert first.download_ids == [IMAGE_ID]
    assert first.record is not None
    first.record.media[IMAGE_ID] = replace(
        first.record.media[IMAGE_ID],
        status=MediaStatus.downloaded,
        path='images/lesson.jpg',
        size=40,
    )
    first.record.sync.page_template = 4

    later = reconcile(
        first.record, live, DiskSnapshot({'images/lesson.jpg': 40}), ALL_FILTERS, NOW
    )

    assert later.download_ids == [
        _media_id(kind) for kind in MediaKind if kind is not MediaKind.image
    ]
    assert later.record is not None
    assert later.record.blocks == live.blocks
    assert later.record.post.updated_at == FIRST
    assert later.record.sync == PostSync(FIRST, NOW, page_template=4)
    assert later.record.media[IMAGE_ID] == first.record.media[IMAGE_ID]


@pytest.mark.parametrize('returned_size', [0, 40])
def test_missing_downloads_stay_deleted_until_restore_or_a_copy_returns(
    returned_size: int,
):
    live = _live(MediaKind.file)
    stored = _stored(live, MediaStatus.downloaded)
    missing = reconcile(stored, live, DiskSnapshot({'files/lesson.zip': 40}), [], NOW)
    assert missing.record is not None
    assert missing.download_ids == []
    assert missing.record.media[FILE_ID] == replace(
        stored.media[FILE_ID], status=MediaStatus.deleted
    )

    restored = reconcile(
        missing.record,
        live,
        DiskSnapshot({'files/lesson.zip': 40}),
        ALL_FILTERS,
        LATER,
        restore_missing=True,
    )
    returned = reconcile(
        missing.record,
        live,
        DiskSnapshot({SAVED_PATH: returned_size}),
        ALL_FILTERS,
        LATER,
    )

    assert restored.download_ids == [FILE_ID]
    assert restored.record is not None
    assert restored.record.media[FILE_ID].status is MediaStatus.pending
    assert returned.download_ids == []
    assert returned.record is not None
    assert returned.record.media[FILE_ID] == replace(
        stored.media[FILE_ID], size=returned_size, error=None
    )


@pytest.mark.parametrize('ready', [False, True])
@pytest.mark.parametrize('selected', [False, True])
def test_file_recovery_precedes_selection_and_does_not_depend_on_readiness(
    *, ready: bool, selected: bool
):
    live = _live(MediaKind.file)
    if not ready:
        live.media[FILE_ID].download = None
    filters = ALL_FILTERS if selected else []

    result = reconcile(None, live, DiskSnapshot({'files/lesson.zip': 40}), filters, NOW)

    assert result.download_ids == []
    assert result.record is not None
    assert result.record.media[FILE_ID] == MediaEntry(
        kind=MediaKind.file,
        status=MediaStatus.downloaded,
        added_at=NOW,
        position=0,
        path='files/lesson.zip',
        size=40,
        filename='lesson.zip',
    )


def test_removed_media_is_never_restored_but_can_return_to_the_download_plan():
    live = _live(MediaKind.file)
    stored = _stored(live, MediaStatus.downloaded)
    removed = reconcile(
        stored, _live(), DiskSnapshot({}), ALL_FILTERS, NOW, restore_missing=True
    )
    assert removed.record is not None
    assert removed.download_ids == []
    assert removed.record.media[FILE_ID] == replace(
        stored.media[FILE_ID],
        status=MediaStatus.deleted,
        removed_at=NOW,
    )
    copied = reconcile(
        removed.record, _live(), DiskSnapshot({SAVED_PATH: 0}), ALL_FILTERS, LATER
    )
    assert copied.record is not None
    assert copied.download_ids == []
    assert copied.record.media[FILE_ID].removed_at == NOW

    returned = reconcile(
        copied.record, live, DiskSnapshot({}), ALL_FILTERS, LATER, restore_missing=True
    )

    assert returned.download_ids == [FILE_ID]
    assert returned.record is not None
    assert returned.record.media[FILE_ID] == replace(
        stored.media[FILE_ID],
        status=MediaStatus.pending,
        size=0,
        error=None,
    )


def test_download_ids_follow_current_body_order_and_ignore_duplicate_references():
    live = _live(MediaKind.file, MediaKind.audio, MediaKind.image)
    stored = _stored(live, MediaStatus.pending)
    live.blocks = [MediaBlock(IMAGE_ID), MediaBlock(FILE_ID), MediaBlock(IMAGE_ID)]
    del live.media[_media_id(MediaKind.audio)]

    result = reconcile(stored, live, DiskSnapshot({}), ALL_FILTERS, NOW)

    assert result.download_ids == [IMAGE_ID, FILE_ID]
    assert result.record is not None
    assert result.record.blocks == live.blocks
    assert result.record.media[_media_id(MediaKind.audio)].removed_at == NOW


def test_the_public_result_owns_its_data_without_changing_any_input():
    live = _live(MediaKind.file)
    stored = _stored(live, MediaStatus.failed)
    disk = DiskSnapshot({}, occupied={'unrelated'}, aliases={'saved': SAVED_PATH})
    filters = [DownloadContentTypeFilter.files]
    checked: set[str] = set()
    original = deepcopy((stored, live, disk, filters, checked))

    result = reconcile(
        stored, live, disk, filters, NOW, checked_unavailable_ids=checked
    )

    assert result.record is not None
    text = result.record.blocks[0]
    assert isinstance(text, TextBlock)
    fragment = text.fragments[0]
    assert isinstance(fragment, PostDataChunkText.TextFragment)
    fragment.style.bold = True
    result.record.post.tags.append('local edit')
    result.record.media[FILE_ID].path = 'edited'
    result.record.sync.page_template = 99
    result.download_ids.clear()
    assert (stored, live, disk, filters, checked) == original


def test_an_edited_post_keeps_old_downloads_and_schedules_a_new_same_named_piece():
    live = _live(MediaKind.image, MediaKind.file)
    stored = _stored(live, MediaStatus.downloaded)
    stored.media[FILE_ID].path = 'files/lesson.zip'
    new_id = 'file:new'
    new_media = live.media.pop(FILE_ID)
    assert isinstance(new_media.download, PostDataChunkFile)
    new_media.download = replace(new_media.download, id='new')
    live.media[new_id] = new_media
    live.blocks = [MediaBlock(IMAGE_ID), MediaBlock(new_id)]
    disk = DiskSnapshot({'saved/image': 12, 'files/lesson.zip': 12})

    result = reconcile(stored, live, disk, ALL_FILTERS, NOW)

    assert result.download_ids == [new_id]
    assert result.record is not None
    assert result.record.media[IMAGE_ID] == replace(stored.media[IMAGE_ID], error=None)
    assert result.record.media[FILE_ID] == replace(
        stored.media[FILE_ID], removed_at=NOW, error=None
    )
    assert result.record.media[new_id].status is MediaStatus.pending
    assert result.record.media[new_id].path is None


def test_an_unavailable_external_url_is_checked_independently_in_each_post():
    first_live = _live(MediaKind.external_video)
    second_live = deepcopy(first_live)
    second_live.post = replace(
        second_live.post, id='other', url='https://boosty.to/fixture/posts/other'
    )
    first_stored = _stored(first_live, MediaStatus.unavailable)
    second_stored = _stored(second_live, MediaStatus.unavailable)
    media_id = _media_id(MediaKind.external_video)

    first = reconcile(
        first_stored,
        first_live,
        DiskSnapshot({}),
        ALL_FILTERS,
        NOW,
        checked_unavailable_ids={media_id},
    )
    second = reconcile(second_stored, second_live, DiskSnapshot({}), ALL_FILTERS, NOW)

    assert first.download_ids == []
    assert second.download_ids == [media_id]
    assert first.record is not None
    assert second.record is not None
    assert first.record.media[media_id] == first_stored.media[media_id]
    assert second.record.media[media_id] == second_stored.media[media_id]
