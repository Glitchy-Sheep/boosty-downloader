"""Previews and primary media keep distinct ownership across retries and recovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast
from unicodedata import normalize
from unittest.mock import AsyncMock, Mock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient
from support.synthetic_post import (
    IMAGE_ID,
    POST_ID,
    image_chunk,
    ok_video_chunk,
    synthetic_post,
)

from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.ports import FailureLog, ProgressReporter
from boosty_downloader.application.post_download_state import (
    PostDownloadState,
    PostRunProgress,
)
from boosty_downloader.application.post_preparation import PostPreparer
from boosty_downloader.application.preview_sync import ensure_post_previews
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.media_output_paths import create_media_parent
from boosty_downloader.infrastructure.media_publication import PublishedFile

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from boosty_downloader.application.post_preparation import PreparedPost
    from boosty_downloader.domain.stored_post import StoredPost
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )

AUTHOR = 'fixture-author'
VIDEO_ID = 'fixture-café'
VIDEO_MEDIA_ID = f'{MediaKind.boosty_video.value}:{VIDEO_ID}'
IMAGE_MEDIA_ID = f'{MediaKind.image.value}:{IMAGE_ID}'
PREVIEW_PATH = f'previews/{VIDEO_ID}.png'
PREVIEW_BYTES = b'preview image bytes'
PRIMARY_BYTES = b'primary image bytes'
COLLIDING_PATHS = [PREVIEW_PATH, PREVIEW_PATH.upper(), normalize('NFD', PREVIEW_PATH)]


@dataclass
class _Attempt:
    prepared: PreparedPost
    state: PostDownloadState


@dataclass
class _Run:
    context: DownloadContext
    store: JsonPostStore
    post: PostDTO

    def prepare(self) -> _Attempt:
        prepared = PostPreparer(
            self.context.library_root, self.store, AUTHOR, BoostyOkVideoType.medium
        ).prepare(self.post, self.context.filters, datetime.now(timezone.utc))
        state = PostDownloadState(
            self.context.library_root, self.store, prepared, PostRunProgress()
        )
        state.save_initial()
        return _Attempt(prepared, state)

    def saved(self) -> StoredPost:
        located = self.store.find_post(AUTHOR, POST_ID)
        assert located is not None
        assert located.record is not None
        return located.record

    def retain_primary(self, path: str, status: MediaStatus) -> None:
        attempt = self.prepare()
        record = self.saved()
        entry = record.media[IMAGE_MEDIA_ID]
        entry.path = path
        entry.status = status
        self.store.save_post(attempt.state.folder, record)

    async def previews(self, attempt: _Attempt) -> None:
        await ensure_post_previews(self.context, attempt.state, attempt.prepared)


def _post(preview_url: str) -> PostDTO:
    payload = synthetic_post()
    payload['data'] = [
        {**image_chunk(), 'size': None},
        {**ok_video_chunk(), 'id': VIDEO_ID, 'preview': preview_url},
    ]
    return PostDTO.model_validate(payload)


async def _image(_: web.Request) -> web.Response:
    return web.Response(body=PREVIEW_BYTES, content_type='image/png')


@pytest.fixture
async def run(tmp_path: Path) -> AsyncGenerator[_Run, None]:
    app = web.Application()
    app.router.add_get('/preview', _image)
    store = JsonPostStore(tmp_path / 'library')
    async with (
        TestServer(app) as server,
        RetryClient(retry_options=ExponentialRetry(attempts=1)) as session,
    ):
        context = DownloadContext(
            author_name=AUTHOR,
            downloader_session=session,
            external_videos_downloader=cast('ExternalVideosDownloader', None),
            post_store=store,
            library_root=tmp_path / 'library',
            filters=[DownloadContentTypeFilter.post_content],
            preferred_video_quality=BoostyOkVideoType.medium,
            progress_reporter=Mock(spec=ProgressReporter),
            failed_logger=AsyncMock(spec=FailureLog),
        )
        yield _Run(context, store, _post(str(server.make_url('/preview'))))


@pytest.mark.parametrize('primary_path', COLLIDING_PATHS, ids=['exact', 'case', 'nfd'])
async def test_missing_primary_reservation_survives_preview_and_its_own_publication(
    run: _Run, primary_path: str
) -> None:
    run.retain_primary(primary_path, MediaStatus.pending)
    attempt = run.prepare()

    await run.previews(attempt)
    target = attempt.state.reserve(IMAGE_MEDIA_ID, 'original.png')
    destination = create_media_parent(
        target.library_root, target.post_folder, target.relative_path
    )
    destination.write_bytes(PRIMARY_BYTES)
    attempt.state.complete(
        IMAGE_MEDIA_ID, PublishedFile(destination, len(PRIMARY_BYTES))
    )

    record = run.saved()
    preview_path = record.media[VIDEO_MEDIA_ID].preview_path
    assert preview_path is not None
    assert _path_key(preview_path) != _path_key(primary_path)
    assert _path_key(target.relative_path) == _path_key(primary_path)
    assert destination.read_bytes() == PRIMARY_BYTES
    assert (destination.parents[1] / preview_path).read_bytes() == PREVIEW_BYTES
    retry = run.prepare()
    assert retry.state.record.media[IMAGE_MEDIA_ID].status is MediaStatus.downloaded
    assert retry.prepared.preview_download_ids == ()


@pytest.mark.parametrize('primary_path', COLLIDING_PATHS, ids=['exact', 'case', 'nfd'])
@pytest.mark.parametrize('removed', [False, True], ids=['current', 'removed'])
async def test_deleted_primary_is_not_recovered_from_new_preview_on_next_attempt(
    run: _Run, primary_path: str, *, removed: bool
) -> None:
    run.retain_primary(primary_path, MediaStatus.deleted)
    if removed:
        run.post.data = [
            chunk for chunk in run.post.data if getattr(chunk, 'id', None) != IMAGE_ID
        ]
    attempt = run.prepare()

    await run.previews(attempt)
    retry = run.prepare()

    entry = retry.state.record.media[IMAGE_MEDIA_ID]
    assert entry.status is MediaStatus.deleted
    assert entry.path == primary_path
    assert (entry.removed_at is not None) is removed
    assert IMAGE_MEDIA_ID not in retry.prepared.reconciliation.download_ids
    assert not (run.context.library_root / retry.state.folder / primary_path).exists()
    assert retry.prepared.preview_download_ids == ()


@pytest.mark.parametrize('preview_path', COLLIDING_PATHS, ids=['exact', 'case', 'nfd'])
@pytest.mark.parametrize('removed', [False, True], ids=['current', 'removed'])
def test_absent_preview_reservation_blocks_primary_allocation(
    run: _Run, preview_path: str, *, removed: bool
) -> None:
    run.retain_primary(PREVIEW_PATH, MediaStatus.pending)
    record = run.saved()
    record.media[VIDEO_MEDIA_ID].preview_path = preview_path
    run.store.save_post(run.prepare().state.folder, record)
    if removed:
        run.post.data = [
            chunk for chunk in run.post.data if getattr(chunk, 'id', None) != VIDEO_ID
        ]
    attempt = run.prepare()

    target = attempt.state.reserve(IMAGE_MEDIA_ID, 'original.png')

    assert _path_key(target.relative_path) != _path_key(preview_path)
    assert run.saved().media[VIDEO_MEDIA_ID].preview_path == preview_path


@pytest.mark.parametrize('preview_path', COLLIDING_PATHS, ids=['exact', 'case', 'nfd'])
def test_saved_preview_cannot_be_recovered_as_pending_primary_media(
    run: _Run, preview_path: str
) -> None:
    run.retain_primary(PREVIEW_PATH, MediaStatus.pending)
    attempt = run.prepare()
    record = run.saved()
    record.media[VIDEO_MEDIA_ID].preview_path = preview_path
    run.store.save_post(attempt.state.folder, record)
    image = run.context.library_root / attempt.state.folder / PREVIEW_PATH
    image.parent.mkdir(parents=True)
    image.write_bytes(PREVIEW_BYTES)

    retry = run.prepare()

    entry = retry.state.record.media[IMAGE_MEDIA_ID]
    assert entry.status is MediaStatus.pending
    assert entry.size is None
    assert IMAGE_MEDIA_ID in retry.prepared.reconciliation.download_ids


def _path_key(path: str) -> str:
    return normalize('NFC', path).casefold()


@pytest.mark.parametrize(
    'preview_path',
    [
        'images/Café.png/retained-preview.png',
        'IMAGES/CAFÉ.PNG/retained-preview.png',
        'images/Cafe\u0301.png/retained-preview.png',
    ],
    ids=['exact', 'case', 'nfd'],
)
def test_primary_publication_keeps_a_missing_previews_parent_available(
    run: _Run, preview_path: str
) -> None:
    first = run.prepare()
    record = run.saved()
    record.media[VIDEO_MEDIA_ID].preview_path = preview_path
    run.store.save_post(first.state.folder, record)
    run.post.data = [
        chunk for chunk in run.post.data if getattr(chunk, 'id', None) != VIDEO_ID
    ]
    attempt = run.prepare()

    target = attempt.state.reserve(IMAGE_MEDIA_ID, 'Café.png')
    destination = create_media_parent(
        target.library_root, target.post_folder, target.relative_path
    )
    destination.write_bytes(PRIMARY_BYTES)
    attempt.state.complete(
        IMAGE_MEDIA_ID, PublishedFile(destination, len(PRIMARY_BYTES))
    )
    retry = run.prepare()

    assert _path_key(target.relative_path) != _path_key('images/Café.png')
    assert retry.state.record.media[IMAGE_MEDIA_ID].status is MediaStatus.downloaded
    retained = retry.state.record.media[VIDEO_MEDIA_ID]
    assert retained.removed_at is not None
    assert retained.preview_path == preview_path
