"""Committed pieces survive writer death and native orphan files recover in place."""

from __future__ import annotations

from contextlib import closing
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from multiprocessing import get_context
from shutil import rmtree
from typing import TYPE_CHECKING, cast

import pytest
from sqlalchemy import select
from support.db_post_interruption import (
    COMMITTED_TERM,
    INTERRUPTED_TERM,
    LibraryObservation,
    MediaObservation,
    ProjectionObservation,
    SaveRequest,
    pause_before_commit,
    pause_before_publication,
    read_restarted_library,
)
from support.synthetic_post import POST_ID

from boosty_downloader.application.mappers.live_post import LiveMedia, LivePost
from boosty_downloader.application.reconcile import reconcile
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
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
from boosty_downloader.infrastructure.library._db_models import DbMarks, DbPost
from boosty_downloader.infrastructure.library.db_post_records import DatabasePostRecords
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase
from boosty_downloader.infrastructure.library.media_snapshot import read_media_snapshot

if TYPE_CHECKING:
    from multiprocessing.process import BaseProcess
    from pathlib import Path

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
AUTHOR = 'fixture-author'
FIRST_ID = 'file:first'
SECOND_ID = 'file:second'
MEDIA_BYTES = b'retained native media'
PROCESS_TIMEOUT = 20


def _pending_record() -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            id=POST_ID,
            author=AUTHOR,
            url='https://boosty.to/example',
            title=COMMITTED_TERM,
            created_at=NOW,
            updated_at=NOW,
            tags=['committed'],
        ),
        sync=PostSync(NOW, NOW),
        blocks=[
            TextBlock([PostDataChunkText.TextFragment(COMMITTED_TERM)]),
            MediaBlock(FIRST_ID),
            MediaBlock(SECOND_ID),
        ],
        media={
            media_id: MediaEntry(
                kind=MediaKind.file,
                status=MediaStatus.pending,
                added_at=NOW,
                position=position,
            )
            for position, media_id in enumerate((FIRST_ID, SECOND_ID))
        },
    )


def _save_committed_piece(store: DatabasePostRecords, folder: str) -> StoredPost:
    record = _pending_record()
    store.save_post(folder, record)
    record.media[FIRST_ID].path = 'files/first.bin'
    store.save_post(folder, record)
    assert store.find_post(AUTHOR, POST_ID) == LocatedPost(folder, record)
    record.media[FIRST_ID].status = MediaStatus.downloaded
    record.media[FIRST_ID].size = len(MEDIA_BYTES)
    store.save_post(folder, record)
    record.media[SECOND_ID].path = 'files/second.bin'
    store.save_post(folder, record)
    assert store.find_post(AUTHOR, POST_ID) == LocatedPost(folder, record)
    return record


def _next_piece(record: StoredPost) -> StoredPost:
    updated = deepcopy(record)
    updated.post.title = INTERRUPTED_TERM
    updated.post.tags = ['uncommitted']
    updated.blocks[0] = TextBlock([PostDataChunkText.TextFragment(INTERRUPTED_TERM)])
    updated.sync.page_template = 9
    updated.media[FIRST_ID].size = 999
    updated.media[SECOND_ID].status = MediaStatus.downloaded
    updated.media[SECOND_ID].size = 100
    return updated


def _stop_process(process: BaseProcess) -> None:
    if process.is_alive():
        process.kill()
    process.join(timeout=PROCESS_TIMEOUT)
    assert not process.is_alive(), 'Child process did not terminate'
    process.close()


def _kill_flushed_writer(
    request: SaveRequest, *, before_publication: bool = False
) -> ProjectionObservation:
    context = get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    release = context.Event()
    target = pause_before_publication if before_publication else pause_before_commit
    process = context.Process(target=target, args=(request, sender, release))
    with closing(receiver), closing(sender):
        process.start()
        sender.close()
        try:
            assert receiver.poll(PROCESS_TIMEOUT), (
                'Writer did not reach its commit boundary'
            )
            projection = cast('ProjectionObservation', receiver.recv())
            assert isinstance(projection, ProjectionObservation)
            assert process.is_alive(), 'Writer committed before the termination point'
            process.kill()
            process.join(timeout=PROCESS_TIMEOUT)
            assert process.exitcode not in {None, 0}
            return projection
        finally:
            _stop_process(process)


def _read_in_fresh_process(request: SaveRequest) -> LibraryObservation:
    context = get_context('spawn')
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=read_restarted_library, args=(request, sender))
    with closing(receiver), closing(sender):
        process.start()
        sender.close()
        try:
            assert receiver.poll(PROCESS_TIMEOUT), (
                'Fresh reader did not return a snapshot'
            )
            observed = cast('LibraryObservation', receiver.recv())
            process.join(timeout=PROCESS_TIMEOUT)
            assert process.exitcode == 0
            assert isinstance(observed, LibraryObservation)
            return observed
        finally:
            _stop_process(process)


def test_writer_killed_after_flush_retains_the_last_committed_piece(tmp_path: Path):
    root = tmp_path / 'library'
    database_path = tmp_path / 'library.db'
    with LibraryDatabase.create(database_path) as database:
        store = DatabasePostRecords(root, database)
        folder = store.choose_post_folder(_pending_record().post)
        committed = _save_committed_piece(store, folder)
    request = SaveRequest(root, database_path, folder, _next_piece(committed))

    flushed = _kill_flushed_writer(request)
    recovered = _read_in_fresh_process(request)

    assert flushed.title == flushed.body == INTERRUPTED_TERM
    assert flushed.tags == ['uncommitted']
    assert flushed.media[SECOND_ID] == MediaObservation(
        MediaStatus.downloaded, 'files/second.bin', 100
    )
    assert flushed.media[FIRST_ID].size == 999
    assert flushed.committed_matches == []
    assert flushed.interrupted_matches == [flushed.row_id]
    assert recovered.located == LocatedPost(folder, committed)
    assert recovered.projection.title == recovered.projection.body == COMMITTED_TERM
    assert recovered.projection.tags == ['committed']
    assert recovered.projection.media == {
        FIRST_ID: MediaObservation(
            MediaStatus.downloaded, 'files/first.bin', len(MEDIA_BYTES)
        ),
        SECOND_ID: MediaObservation(MediaStatus.pending, 'files/second.bin', None),
    }
    assert recovered.projection.committed_matches == [recovered.projection.row_id]
    assert recovered.projection.interrupted_matches == []
    assert recovered.integrity == 'ok'


@pytest.mark.parametrize('before_publication', [False, True])
def test_killed_missing_folder_save_never_revives_the_previous_generation(
    tmp_path: Path,
    *,
    before_publication: bool,
):
    root = tmp_path / 'library'
    database_path = tmp_path / 'library.db'
    with LibraryDatabase.create(database_path) as database:
        store = DatabasePostRecords(root, database)
        folder = store.choose_post_folder(_pending_record().post)
        committed = _save_committed_piece(store, folder)
        with database.transaction() as session:
            row = session.scalars(select(DbPost)).one()
            session.add(DbMarks(post_row_id=row.id, favorite=True))
        rmtree(root / folder)
        assert store.find_post(AUTHOR, POST_ID) is None
    request = SaveRequest(root, database_path, folder, _next_piece(committed))

    _kill_flushed_writer(request, before_publication=before_publication)
    recovered = _read_in_fresh_process(request)

    assert recovered.located is None
    assert not (root / folder).exists()
    assert recovered.integrity == 'ok'
    if before_publication:
        assert recovered.projection.title == INTERRUPTED_TERM
        assert recovered.favorite is None
    else:
        assert recovered.projection.title == COMMITTED_TERM
        assert recovered.favorite is True
    with LibraryDatabase.open(database_path, writable=True) as database:
        store = DatabasePostRecords(root, database)
        store.save_post(folder, request.record)
        assert store.find_post(AUTHOR, POST_ID) == LocatedPost(folder, request.record)
        with database.transaction() as session:
            assert list(session.scalars(select(DbMarks))) == []


@pytest.mark.parametrize(
    ('media', 'media_path'),
    [
        pytest.param(
            LiveMedia(
                kind=MediaKind.image,
                download=PostDataChunkImage(
                    id='fixture', url='https://cdn.example/image'
                ),
                expected_size=len(MEDIA_BYTES),
            ),
            'images/image.jpg',
            id='image',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.file,
                download=PostDataChunkFile(
                    id='fixture',
                    url='https://cdn.example/file',
                    filename='lesson.zip',
                ),
                expected_size=len(MEDIA_BYTES),
                filename='lesson.zip',
            ),
            'files/lesson.zip',
            id='file',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.audio,
                download=PostDataChunkAudio(
                    id='fixture',
                    url='https://cdn.example/audio',
                    title='lesson.mp3',
                ),
                expected_size=len(MEDIA_BYTES),
                title='lesson.mp3',
            ),
            'audio/lesson.mp3',
            id='audio',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.boosty_video,
                download=PostDataChunkBoostyVideo(
                    id='fixture',
                    title='Lesson',
                    url='https://cdn.example/video',
                    quality='high',
                ),
                title='Lesson',
            ),
            'boosty_videos/Lesson (fixture).mp4',
            id='boosty-video',
        ),
    ],
)
def test_native_orphan_is_reconciled_without_transfer_or_file_changes(
    tmp_path: Path, media: LiveMedia, media_path: str
):
    root = tmp_path / 'library'
    with LibraryDatabase.create(tmp_path / 'library.db') as database:
        store = DatabasePostRecords(root, database)
        metadata = _pending_record().post
        folder = store.choose_post_folder(metadata)
        retained = _seed_retained_files(root / folder, media_path)
        modified = {path: path.stat().st_mtime_ns for path in retained}
        paths = set(root.rglob('*'))
        located = store.find_post(AUTHOR, POST_ID)
        assert located == LocatedPost(folder)
        assert located is not None
        media_id = f'{media.kind.value}:fixture'
        live = LivePost(
            post=replace(metadata, title='Renamed remote title'),
            has_access=True,
            blocks=[MediaBlock(media_id)],
            media={media_id: media},
        )

        result = reconcile(
            located.record,
            live,
            read_media_snapshot(root, folder),
            list(DownloadContentTypeFilter),
            NOW,
        )

        assert result.download_ids == []
        assert result.record is not None
        entry = result.record.media[media_id]
        assert entry.status is MediaStatus.downloaded
        assert entry.path == media_path
        assert entry.size == len(MEDIA_BYTES)
        store.save_post(folder, result.record)
        assert DatabasePostRecords(root, database).find_post(
            AUTHOR, POST_ID
        ) == LocatedPost(folder, result.record)
    assert set(root.rglob('*')) == paths
    assert {path: path.read_bytes() for path in retained} == retained
    assert {path: path.stat().st_mtime_ns for path in retained} == modified
    assert not (root / folder / 'post.json').exists()


def _seed_retained_files(folder: Path, media_path: str) -> dict[Path, bytes]:
    retained = {
        folder / media_path: MEDIA_BYTES,
        folder / 'post.html': b'<p>Retained page</p>',
        folder / 'notes.txt': b'User notes',
    }
    for path, content in retained.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return retained
