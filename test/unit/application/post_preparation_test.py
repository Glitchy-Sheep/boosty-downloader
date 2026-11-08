"""Shared preparation observes saved progress without changing the library."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from support.synthetic_post import (
    FILE_ID,
    FILE_NAME,
    IMAGE_ID,
    VIDEO_ID,
    file_chunk,
    image_chunk,
    ok_video_chunk,
    synthetic_post,
    text_chunk,
)

from boosty_downloader.application import post_preparation
from boosty_downloader.application.mappers.live_post import map_post_dto_to_live
from boosty_downloader.application.post_preparation import PostPreparer, PreparedPost
from boosty_downloader.application.reconcile import prepare_record
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.stored_post import (
    LockedPost,
    MediaKind,
    MediaStatus,
    StoredPost,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library import media_snapshot
from boosty_downloader.infrastructure.library.author_records import read_locked_posts
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=7)
AUTHOR = 'fixture-author'
IMAGE_MEDIA_ID = f'image:{IMAGE_ID}'
FILE_MEDIA_ID = f'file:{FILE_ID}'
VIDEO_MEDIA_ID = f'boosty_video:{VIDEO_ID}'
ALL_FILTERS = tuple(DownloadContentTypeFilter)
IMAGE_BYTES = b'picture'
FILE_BYTES = b'archive'
VIDEO_BYTES = b'video'


@dataclass(frozen=True, slots=True)
class SavedPost:
    folder: str
    record: StoredPost


@dataclass(frozen=True, slots=True)
class FileState:
    data: bytes
    modified_ns: int


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'library'


@pytest.fixture
def preparer(root: Path) -> PostPreparer:
    return PostPreparer(root, JsonPostStore(root), AUTHOR, BoostyOkVideoType.medium)


@pytest.fixture
def post() -> PostDTO:
    payload = synthetic_post()
    payload['data'] = [
        text_chunk('A complete lesson'),
        {**image_chunk(), 'size': len(IMAGE_BYTES)},
        {**file_chunk(), 'size': len(FILE_BYTES)},
        ok_video_chunk(),
    ]
    return PostDTO.model_validate(payload)


def _text_post() -> PostDTO:
    payload = synthetic_post()
    payload['data'] = [text_chunk('A complete lesson')]
    return PostDTO.model_validate(payload)


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _seed(
    preparer: PostPreparer,
    post: PostDTO,
    *,
    page_exists: bool = True,
    page_template: int | None = PAGE_TEMPLATE_VERSION,
) -> SavedPost:
    live = map_post_dto_to_live(post, AUTHOR, BoostyOkVideoType.medium)
    record = prepare_record(None, live, NOW)
    assert record is not None
    record.sync.page_template = page_template
    folder = preparer.store.choose_post_folder(record.post)
    preparer.store.save_post(folder, record)
    if page_exists:
        _write(preparer.library_root / folder / 'post.html', b'<p>Saved page</p>')
    return SavedPost(folder, record)


def _record(prepared: PreparedPost) -> StoredPost:
    record = prepared.reconciliation.record
    assert record is not None
    return record


def _files(root: Path) -> dict[Path, FileState]:
    return {
        path.relative_to(root): FileState(path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob('*')
        if path.is_file()
    }


def _complete(
    preparer: PostPreparer,
    prepared: PreparedPost,
    media_id: str,
    path: str,
    data: bytes,
) -> None:
    _write(preparer.library_root / prepared.folder / path, data)
    entry = _record(prepared).media[media_id]
    entry.path = path
    entry.size = len(data)
    entry.status = MediaStatus.downloaded


def test_new_post_keeps_complete_body_and_plans_only_selected_media(
    preparer: PostPreparer, post: PostDTO, root: Path
) -> None:
    before = post.model_dump()

    prepared = preparer.prepare(post, [DownloadContentTypeFilter.files], NOW)

    assert prepared.is_new
    assert prepared.stored is None
    assert prepared.needs_update
    assert prepared.page_needs_update
    assert not prepared.page_exists
    assert prepared.reconciliation.download_ids == [FILE_MEDIA_ID]
    assert set(_record(prepared).media) == {
        IMAGE_MEDIA_ID,
        FILE_MEDIA_ID,
        VIDEO_MEDIA_ID,
    }
    assert len(_record(prepared).blocks) == 4
    assert _record(prepared).sync.first_downloaded_at == NOW
    assert prepared.live.media[FILE_MEDIA_ID].expected_size == len(FILE_BYTES)
    assert prepared.live.media[VIDEO_MEDIA_ID].expected_size is None
    assert post.model_dump() == before
    assert not root.exists()


@pytest.mark.parametrize('empty_body', [False, True])
def test_accessible_post_without_selected_media_still_has_record(
    preparer: PostPreparer, root: Path, *, empty_body: bool
) -> None:
    post = _text_post()
    if empty_body:
        post = post.model_copy(update={'data': []})

    prepared = preparer.prepare(post, [], NOW)

    assert prepared.is_new
    assert prepared.needs_update
    assert prepared.reconciliation.download_ids == []
    assert _record(prepared).media == {}
    assert bool(_record(prepared).blocks) is not empty_body
    assert not root.exists()


def test_later_run_plans_only_missing_pieces_and_then_becomes_unchanged(
    preparer: PostPreparer, post: PostDTO
) -> None:
    first = preparer.prepare(post, [DownloadContentTypeFilter.post_content], NOW)
    assert first.reconciliation.download_ids == [IMAGE_MEDIA_ID]
    _complete(preparer, first, IMAGE_MEDIA_ID, 'images/cover.jpg', IMAGE_BYTES)
    _record(first).sync.page_template = PAGE_TEMPLATE_VERSION
    preparer.store.save_post(first.folder, _record(first))
    _write(preparer.library_root / first.folder / 'post.html', b'<p>Full body</p>')

    second = preparer.prepare(post, ALL_FILTERS, LATER)

    assert not second.is_new
    assert second.folder == first.folder
    assert second.reconciliation.download_ids == [FILE_MEDIA_ID, VIDEO_MEDIA_ID]
    assert second.needs_update
    assert not second.record_changed
    assert _record(second).media[IMAGE_MEDIA_ID].status is MediaStatus.downloaded
    _complete(preparer, second, FILE_MEDIA_ID, f'files/{FILE_NAME}', FILE_BYTES)
    _complete(preparer, second, VIDEO_MEDIA_ID, 'boosty_videos/lesson.mp4', VIDEO_BYTES)
    preparer.store.save_post(second.folder, _record(second))

    third = preparer.prepare(post, ALL_FILTERS, LATER + timedelta(days=1))

    assert third.reconciliation.download_ids == []
    assert not third.record_changed
    assert not third.page_needs_update
    assert not third.needs_update


def test_existing_unchanged_post_preserves_files_and_original_snapshot(
    preparer: PostPreparer, root: Path
) -> None:
    post = _text_post()
    saved = _seed(preparer, post)
    _write(root / saved.folder / 'viewer.json', b'User viewing marks')
    _write(root / saved.folder / 'notes.txt', b'Personal notes')
    locked = LockedPost(deepcopy(saved.record.post), NOW)
    preparer.store.save_locked_post(locked)
    before = _files(root)

    prepared = preparer.prepare(post, ALL_FILTERS, LATER)

    assert not prepared.record_changed
    assert not prepared.needs_update
    assert prepared.stored is not None
    assert prepared.stored == saved.record
    assert prepared.stored is not _record(prepared)
    assert _record(prepared).sync.synced_at == LATER
    assert prepared.stored.sync.synced_at == NOW
    assert _files(root) == before
    assert read_locked_posts(root, AUTHOR) == {post.id: locked}
    _record(prepared).post.tags.append('local mutation')
    assert prepared.stored.post.tags == saved.record.post.tags
    assert prepared.live.post.tags == saved.record.post.tags


@pytest.mark.parametrize(
    ('page_exists', 'page_template', 'needs_update'),
    [
        (True, PAGE_TEMPLATE_VERSION, False),
        (False, PAGE_TEMPLATE_VERSION, True),
        (True, None, True),
        (True, PAGE_TEMPLATE_VERSION + 1, True),
    ],
)
def test_page_presence_and_saved_template_are_separate_from_record_changes(
    preparer: PostPreparer,
    *,
    page_exists: bool,
    page_template: int | None,
    needs_update: bool,
) -> None:
    post = _text_post()
    _seed(preparer, post, page_exists=page_exists, page_template=page_template)

    prepared = preparer.prepare(post, [], LATER)

    assert prepared.page_exists is page_exists
    assert prepared.page_needs_update is needs_update
    assert prepared.needs_update is needs_update
    assert not prepared.record_changed


def test_renamed_post_keeps_saved_folder_and_reports_metadata_change(
    preparer: PostPreparer,
) -> None:
    post = _text_post()
    saved = _seed(preparer, post)
    renamed = post.model_copy(update={'title': 'Renamed lesson'})

    prepared = preparer.prepare(renamed, [], LATER)

    assert prepared.folder == saved.folder
    assert prepared.stored == saved.record
    assert _record(prepared).post.title == 'Renamed lesson'
    assert prepared.record_changed
    assert prepared.needs_update


def test_body_change_is_material_without_metadata_change(
    preparer: PostPreparer,
) -> None:
    post = _text_post()
    _seed(preparer, post)
    payload = post.model_dump(by_alias=True)
    payload['data'] = [text_chunk('Updated body')]

    prepared = preparer.prepare(PostDTO.model_validate(payload), [], LATER)

    assert prepared.stored is not None
    assert prepared.stored.post == _record(prepared).post
    assert prepared.stored.blocks != _record(prepared).blocks
    assert prepared.record_changed
    assert prepared.needs_update


def test_recordless_folder_is_reused_and_retained_file_is_recovered(
    preparer: PostPreparer, post: PostDTO, root: Path
) -> None:
    live = map_post_dto_to_live(post, AUTHOR, BoostyOkVideoType.medium)
    folder = preparer.store.choose_post_folder(live.post)
    _write(root / folder / 'files' / FILE_NAME, FILE_BYTES)
    _write(root / folder / 'viewer.json', b'Retained marks')
    before = _files(root)
    renamed = post.model_copy(update={'title': 'Renamed after record loss'})

    prepared = preparer.prepare(renamed, ALL_FILTERS, NOW)

    assert prepared.is_new
    assert prepared.folder == folder
    assert prepared.stored is None
    assert _record(prepared).media[FILE_MEDIA_ID].status is MediaStatus.downloaded
    assert prepared.reconciliation.download_ids == [IMAGE_MEDIA_ID, VIDEO_MEDIA_ID]
    assert _files(root) == before


@pytest.mark.parametrize('removed_file', [False, True])
def test_local_file_changes_are_material_without_planned_downloads(
    preparer: PostPreparer, post: PostDTO, root: Path, *, removed_file: bool
) -> None:
    saved = _seed(preparer, post)
    entry = saved.record.media[FILE_MEDIA_ID]
    entry.status = MediaStatus.downloaded
    entry.path = f'files/{FILE_NAME}'
    entry.size = len(FILE_BYTES)
    preparer.store.save_post(saved.folder, saved.record)
    if not removed_file:
        _write(root / saved.folder / entry.path, b'User-edited file')

    prepared = preparer.prepare(post, [], LATER)

    assert prepared.reconciliation.download_ids == []
    assert prepared.record_changed
    assert prepared.needs_update
    actual = _record(prepared).media[FILE_MEDIA_ID]
    if removed_file:
        assert actual.status is MediaStatus.deleted
    else:
        assert actual.status is MediaStatus.downloaded
        assert actual.size == len(b'User-edited file')


def test_unfinished_file_keeps_inventory_without_download(
    preparer: PostPreparer,
) -> None:
    payload = synthetic_post()
    payload['data'] = [{**file_chunk(), 'complete': False}]

    prepared = preparer.prepare(PostDTO.model_validate(payload), ALL_FILTERS, NOW)

    assert prepared.reconciliation.download_ids == []
    assert _record(prepared).media[FILE_MEDIA_ID].kind is MediaKind.file
    assert prepared.live.media[FILE_MEDIA_ID].download is None
    assert prepared.is_new


def test_retry_passes_checked_unavailable_ids_without_recording_new_outcomes(
    preparer: PostPreparer, post: PostDTO
) -> None:
    saved = _seed(preparer, post)
    saved.record.media[FILE_MEDIA_ID].status = MediaStatus.unavailable
    saved.record.media[VIDEO_MEDIA_ID].status = MediaStatus.failed
    preparer.store.save_post(saved.folder, saved.record)
    checked = {FILE_MEDIA_ID}

    prepared = preparer.prepare(
        post, ALL_FILTERS, LATER, checked_unavailable_ids=checked
    )

    assert prepared.reconciliation.download_ids == [IMAGE_MEDIA_ID, VIDEO_MEDIA_ID]
    assert checked == {FILE_MEDIA_ID}
    assert _record(prepared).media[FILE_MEDIA_ID].status is MediaStatus.unavailable
    assert _record(prepared).media[VIDEO_MEDIA_ID].status is MediaStatus.failed


def test_locked_post_is_rejected_before_mapping_or_store_lookup(
    preparer: PostPreparer, post: PostDTO, monkeypatch: pytest.MonkeyPatch, root: Path
) -> None:
    def unexpected(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Locked content must not be prepared')

    monkeypatch.setattr(post_preparation, 'map_post_dto_to_live', unexpected)
    monkeypatch.setattr(preparer.store, 'find_post', unexpected)
    locked = post.model_copy(update={'has_access': False})

    with pytest.raises(ValueError, match='locked post'):
        preparer.prepare(locked, ALL_FILTERS, NOW)

    assert not root.exists()


def test_corrupt_record_error_preserves_library(
    preparer: PostPreparer, root: Path
) -> None:
    post = _text_post()
    saved = _seed(preparer, post)
    _write(root / saved.folder / 'post.json', b'{broken record')
    before = _files(root)

    with pytest.raises(InvalidPostRecordError):
        preparer.prepare(post, ALL_FILTERS, LATER)

    assert _files(root) == before


def test_snapshot_access_error_is_not_treated_as_missing_media(
    preparer: PostPreparer, post: PostDTO, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = _seed(preparer, post)
    before = deepcopy(saved.record)

    def denied(_path: object) -> None:
        message = 'Snapshot denied'
        raise PermissionError(message)

    monkeypatch.setattr(media_snapshot, 'scandir', denied)

    with pytest.raises(PermissionError, match='Snapshot denied'):
        preparer.prepare(post, ALL_FILTERS, LATER)

    located = preparer.store.find_post(AUTHOR, post.id)
    assert located is not None
    assert located.record == before


@pytest.mark.parametrize(
    ('preferred_name', 'observed_name'),
    [('lesson.zip', 'LESSON.ZIP'), ('café.zip', 'cafe\u0301.zip')],
    ids=['case', 'unicode'],
)
def test_recordless_media_and_page_aliases_require_filesystem_confirmation(
    preparer: PostPreparer, root: Path, preferred_name: str, observed_name: str
) -> None:
    payload = synthetic_post()
    payload['data'] = [
        {**file_chunk(), 'title': preferred_name, 'size': len(FILE_BYTES)}
    ]
    post = PostDTO.model_validate(payload)
    live = map_post_dto_to_live(post, AUTHOR, BoostyOkVideoType.medium)
    folder = preparer.store.choose_post_folder(live.post)
    post_folder = root / folder
    _write(post_folder / 'files' / observed_name, FILE_BYTES)
    _write(post_folder / 'POST.HTML', b'<p>Saved page</p>')
    media_alias_exists = (post_folder / 'files' / preferred_name).is_file()
    page_alias_exists = (post_folder / 'post.html').is_file()
    before = _files(root)

    prepared = preparer.prepare(post, ALL_FILTERS, NOW)

    assert prepared.folder == folder
    assert prepared.is_new
    assert prepared.page_exists is page_alias_exists
    entry = _record(prepared).media[FILE_MEDIA_ID]
    if media_alias_exists:
        assert entry.status is MediaStatus.downloaded
        assert entry.path in prepared.disk.files
        assert entry.size == len(FILE_BYTES)
        assert prepared.reconciliation.download_ids == []
    else:
        assert entry.status is MediaStatus.pending
        assert entry.path is None
        assert prepared.reconciliation.download_ids == [FILE_MEDIA_ID]
    assert _files(root) == before


def test_directory_named_like_page_does_not_count_as_rendered_page(
    preparer: PostPreparer, root: Path
) -> None:
    post = _text_post()
    saved = _seed(preparer, post, page_exists=False)
    (root / saved.folder / 'post.html').mkdir()

    prepared = preparer.prepare(post, [], LATER)

    assert not prepared.page_exists
    assert prepared.page_needs_update
    assert not prepared.record_changed
    assert prepared.needs_update


@pytest.mark.parametrize('status', [MediaStatus.downloaded, MediaStatus.deleted])
def test_saved_media_paths_still_receive_physical_alias_confirmation(
    preparer: PostPreparer, post: PostDTO, root: Path, status: MediaStatus
) -> None:
    saved = _seed(preparer, post)
    entry = saved.record.media[FILE_MEDIA_ID]
    entry.status = status
    entry.path = f'files/{FILE_NAME}'
    entry.size = len(FILE_BYTES)
    preparer.store.save_post(saved.folder, saved.record)
    actual_path = f'FILES/{FILE_NAME.upper()}'
    _write(root / saved.folder / actual_path, FILE_BYTES)
    alias_exists = (root / saved.folder / entry.path).is_file()
    before = _files(root)

    prepared = preparer.prepare(post, [DownloadContentTypeFilter.files], LATER)

    assert prepared.reconciliation.download_ids == []
    observed = _record(prepared).media[FILE_MEDIA_ID]
    if alias_exists:
        assert observed.status is MediaStatus.downloaded
        assert observed.path == actual_path
        assert prepared.disk.aliases[entry.path] == actual_path
    else:
        assert observed.status is MediaStatus.deleted
        assert observed.path == entry.path
        assert entry.path not in prepared.disk.aliases
    assert _files(root) == before
