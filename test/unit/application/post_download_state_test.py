"""A post owner saves each media outcome without losing peers or retry history."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from support.synthetic_post import POST_ID

from boosty_downloader.application.mappers.live_post import LivePost
from boosty_downloader.application.post_download_state import (
    PostDownloadState,
    PostRunProgress,
)
from boosty_downloader.application.post_preparation import PreparedPost
from boosty_downloader.application.reconcile import ReconcileResult
from boosty_downloader.domain.disk_snapshot import DiskSnapshot
from boosty_downloader.domain.stored_post import (
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.media_publication import PublishedFile

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.infrastructure.media_transfer import MediaTarget

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
AUTHOR = 'fixture-author'
FILE_ID = 'file:fixture-file'
IMAGE_ID = 'image:fixture-image'


@dataclass
class Attempt:
    root: Path
    store: JsonPostStore
    prepared: PreparedPost
    progress: PostRunProgress
    state: PostDownloadState

    def saved(self) -> StoredPost:
        located = self.store.find_post(AUTHOR, POST_ID)
        assert located is not None
        assert located.record is not None
        return located.record

    def retry(self) -> PostDownloadState:
        record = self.saved()
        prepared = replace(
            self.prepared,
            stored=record,
            reconciliation=ReconcileResult(record, list(record.media)),
        )
        return PostDownloadState(self.root, self.store, prepared, self.progress)


@pytest.fixture
def attempt(tmp_path: Path) -> Attempt:
    root = tmp_path / 'library'
    store = JsonPostStore(root)
    post = PostMetadata(
        POST_ID, AUTHOR, 'https://boosty.to/fixture', 'Fixture', NOW, NOW
    )
    media = {
        f'{kind.value}:fixture-{kind.value}': MediaEntry(
            kind=kind, status=MediaStatus.pending, added_at=NOW, position=position
        )
        for position, kind in enumerate(MediaKind)
    }
    record = StoredPost(post, PostSync(NOW, NOW), media=media)
    prepared = PreparedPost(
        live=LivePost(post=post, has_access=True, blocks=[], media={}),
        stored=None,
        folder=store.choose_post_folder(post),
        disk=DiskSnapshot({}),
        reconciliation=ReconcileResult(record, list(media)),
        page_exists=False,
        record_changed=True,
    )
    progress = PostRunProgress()
    state = PostDownloadState(root, store, prepared, progress)
    return Attempt(root, store, prepared, progress, state)


def _publish(target: MediaTarget, content: bytes = b'actual output') -> PublishedFile:
    destination = target.library_root / target.post_folder / target.relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return PublishedFile(destination, len(content))


def _deny_save(_folder: str, _record: StoredPost) -> None:
    message = 'Record save failed'
    raise OSError(message)


@pytest.mark.parametrize(
    ('kind', 'folder'),
    [
        (MediaKind.image, 'images'),
        (MediaKind.file, 'files'),
        (MediaKind.audio, 'audio'),
        (MediaKind.boosty_video, 'boosty_videos'),
        (MediaKind.external_video, 'external_videos'),
    ],
)
def test_reservation_is_saved_before_returning_a_media_target(
    attempt: Attempt, kind: MediaKind, folder: str
) -> None:
    media_id = f'{kind.value}:fixture-{kind.value}'

    target = attempt.state.reserve(media_id, 'ready.bin')

    entry = attempt.saved().media[media_id]
    assert target.relative_path == f'{folder}/ready.bin'
    assert target.media_id == media_id
    assert target.post_folder == attempt.prepared.folder
    assert entry.path == target.relative_path
    assert entry.status is MediaStatus.pending
    assert not (attempt.root / target.post_folder / folder).exists()


def test_failed_reservation_does_not_mutate_owner_or_create_media(
    attempt: Attempt, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = deepcopy(attempt.state.record)
    monkeypatch.setattr(attempt.store, 'save_post', _deny_save)

    with pytest.raises(OSError, match='Record save failed'):
        attempt.state.reserve(FILE_ID, 'archive.zip')

    assert attempt.state.record == before
    assert not attempt.root.exists()


def test_same_suffix_retries_keep_the_reserved_path_after_title_changes(
    attempt: Attempt,
) -> None:
    first = attempt.state.reserve(FILE_ID, 'original.zip')
    attempt.state.fail(FILE_ID, 'Network interrupted')

    second = attempt.retry().reserve(FILE_ID, 'new-title.zip')

    assert second.relative_path == first.relative_path
    assert attempt.saved().media[FILE_ID].error is None


def test_postprocessing_suffix_changes_save_a_new_reservation(attempt: Attempt) -> None:
    first = attempt.state.reserve(FILE_ID, 'lecture.webm')

    second = attempt.state.reserve(FILE_ID, 'lecture.mp4')

    assert first.relative_path == 'files/lecture.webm'
    assert second.relative_path == 'files/lecture.mp4'
    assert attempt.saved().media[FILE_ID].path == second.relative_path


def test_retained_removed_and_deleted_paths_block_new_reservations(
    attempt: Attempt,
) -> None:
    record = deepcopy(attempt.state.record)
    record.media['file:retained'] = MediaEntry(
        kind=MediaKind.file,
        status=MediaStatus.deleted,
        added_at=NOW,
        position=len(record.media),
        removed_at=NOW,
        path='files/shared.zip',
        size=123,
    )
    prepared = replace(
        attempt.prepared,
        reconciliation=ReconcileResult(record, [FILE_ID]),
    )
    state = PostDownloadState(attempt.root, attempt.store, prepared, attempt.progress)

    target = state.reserve(FILE_ID, 'shared.zip')

    assert target.relative_path != 'files/shared.zip'
    assert attempt.saved().media['file:retained'] == record.media['file:retained']


def test_disk_occupied_reservation_uses_a_free_name_without_touching_the_file(
    attempt: Attempt,
) -> None:
    occupied = attempt.root / attempt.state.folder / 'files/archive.zip'
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(b'user bytes')
    prepared = replace(attempt.prepared, disk=DiskSnapshot({'files/archive.zip': 10}))
    state = PostDownloadState(attempt.root, attempt.store, prepared, attempt.progress)

    target = state.reserve(FILE_ID, 'archive.zip')

    assert target.relative_path != 'files/archive.zip'
    assert occupied.read_bytes() == b'user bytes'


def test_completed_peers_keep_their_paths_and_actual_sizes(attempt: Attempt) -> None:
    first = attempt.state.reserve(FILE_ID, 'archive.zip')
    second = attempt.state.reserve(IMAGE_ID, 'image.png')

    assert attempt.state.complete(FILE_ID, _publish(first, b'archive'))
    assert attempt.state.complete(IMAGE_ID, _publish(second, b'picture bytes'))

    saved = attempt.saved()
    assert saved.media[FILE_ID].size == 7
    assert saved.media[IMAGE_ID].size == 13
    assert saved.media[FILE_ID].path == first.relative_path
    assert saved.media[IMAGE_ID].path == second.relative_path
    assert saved.media[FILE_ID].status is MediaStatus.downloaded
    assert saved.media[IMAGE_ID].status is MediaStatus.downloaded


def test_completion_is_counted_once_across_recreated_retry_owner(
    attempt: Attempt,
) -> None:
    target = attempt.state.reserve(FILE_ID, 'archive.zip')
    result = _publish(target)

    assert attempt.state.complete(FILE_ID, result)
    assert not attempt.retry().complete(FILE_ID, result)
    assert attempt.progress.counted_media_ids == {FILE_ID}


def test_failed_completion_save_keeps_pending_state_and_uncounted_progress(
    attempt: Attempt, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = attempt.state.reserve(FILE_ID, 'archive.zip')
    result = _publish(target)
    before = attempt.saved()
    monkeypatch.setattr(attempt.store, 'save_post', _deny_save)

    with pytest.raises(OSError, match='Record save failed'):
        attempt.state.complete(FILE_ID, result)

    assert attempt.saved() == before
    assert attempt.state.record == before
    assert not attempt.progress.counted_media_ids
    assert result.path.read_bytes() == b'actual output'


def test_unavailable_result_is_saved_and_checked_only_once_this_run(
    attempt: Attempt,
) -> None:
    attempt.state.fail(FILE_ID, 'Gone from source', unavailable=True)
    attempt.state.fail(IMAGE_ID, 'Network interrupted')

    assert attempt.saved().media[FILE_ID].status is MediaStatus.unavailable
    assert attempt.saved().media[IMAGE_ID].status is MediaStatus.failed
    assert attempt.progress.checked_unavailable_ids == {FILE_ID}


def test_failed_unavailable_save_does_not_suppress_a_later_retry(
    attempt: Attempt, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = deepcopy(attempt.state.record)
    monkeypatch.setattr(attempt.store, 'save_post', _deny_save)

    with pytest.raises(OSError, match='Record save failed'):
        attempt.state.fail(FILE_ID, 'Gone from source', unavailable=True)

    assert attempt.state.record == before
    assert not attempt.progress.checked_unavailable_ids


@pytest.mark.parametrize('different_path', ['outside.bin', 'files/another.zip'])
def test_completion_rejects_a_result_outside_the_current_reservation(
    attempt: Attempt, different_path: str
) -> None:
    attempt.state.reserve(FILE_ID, 'archive.zip')
    before = attempt.saved()
    result = PublishedFile(attempt.root / different_path, 12)

    with pytest.raises(ValueError, match='saved reservation'):
        attempt.state.complete(FILE_ID, result)

    assert attempt.saved() == before
    assert not attempt.progress.counted_media_ids


def test_completion_rejects_the_obsolete_suffix_reservation(attempt: Attempt) -> None:
    first = attempt.state.reserve(FILE_ID, 'lecture.webm')
    attempt.state.reserve(FILE_ID, 'lecture.mp4')

    with pytest.raises(ValueError, match='saved reservation'):
        attempt.state.complete(FILE_ID, _publish(first))

    assert attempt.saved().media[FILE_ID].path == 'files/lecture.mp4'


def test_refreshed_record_invalidates_the_page_until_render_succeeds(
    attempt: Attempt,
) -> None:
    attempt.state.mark_rendered(7)
    attempt.state.save_initial()

    assert attempt.saved().sync.page_template is None

    attempt.state.mark_rendered(7)

    assert attempt.saved().sync.page_template == 7


def test_media_updates_invalidate_a_previously_rendered_page(attempt: Attempt) -> None:
    attempt.state.mark_rendered(7)
    attempt.state.reserve(FILE_ID, 'archive.zip')

    assert attempt.saved().sync.page_template is None


def test_failed_render_marker_save_keeps_the_page_pending(
    attempt: Attempt, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempt.state.save_initial()
    monkeypatch.setattr(attempt.store, 'save_post', _deny_save)

    with pytest.raises(OSError, match='Record save failed'):
        attempt.state.mark_rendered(7)

    assert attempt.state.record.sync.page_template is None
    assert attempt.saved().sync.page_template is None


def test_owner_does_not_mutate_the_prepared_record(attempt: Attempt) -> None:
    before = deepcopy(attempt.prepared.reconciliation.record)

    attempt.state.reserve(FILE_ID, 'archive.zip')

    assert attempt.prepared.reconciliation.record == before


@pytest.mark.parametrize('filename', ['', '../escape.zip', 'folder/file.zip', 'a\\b'])
def test_invalid_transport_filename_cannot_save_a_reservation(
    attempt: Attempt, filename: str
) -> None:
    with pytest.raises(ValueError, match='without directory components'):
        attempt.state.reserve(FILE_ID, filename)

    assert not attempt.root.exists()


def test_downloaded_media_cannot_reserve_another_output(attempt: Attempt) -> None:
    target = attempt.state.reserve(FILE_ID, 'archive.zip')
    attempt.state.complete(FILE_ID, _publish(target))

    with pytest.raises(ValueError, match='completed media'):
        attempt.state.reserve(FILE_ID, 'replacement.zip')
