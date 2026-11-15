"""Optional images preserve post state while record failures remain visible."""

from __future__ import annotations

from asyncio import CancelledError
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock

import pytest
from support.synthetic_post import (
    POST_ID,
    SIGNED_QUERY,
    TEASER_ID,
    VIDEO_ID,
    ok_video_chunk,
    synthetic_post,
)

from boosty_downloader.application import post_access, preview_sync, thumbnail_sync
from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
)
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.mappers.post_metadata import map_post_metadata
from boosty_downloader.application.ports import FailureLog, ProgressReporter
from boosty_downloader.application.post_download_state import (
    PostDownloadState,
    PostRunProgress,
)
from boosty_downloader.application.post_preparation import PostPreparer
from boosty_downloader.application.post_retry import PostDownloadRetrier
from boosty_downloader.domain.stored_post import (
    LockedPost,
    MediaEntry,
    MediaKind,
    MediaStatus,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadTimeoutError,
)
from boosty_downloader.infrastructure.library.errors import InvalidAuthorRecordError
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from aiohttp_retry import RetryClient

    from boosty_downloader.application.post_preparation import PreparedPost
    from boosty_downloader.domain.stored_post import StoredPost
    from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )

AUTHOR = 'fixture-author'
VIDEO_MEDIA_ID = f'{MediaKind.boosty_video.value}:{VIDEO_ID}'
PREVIEW_PATH = f'previews/{VIDEO_ID}.png'
TEASER_PATH = f'.boosty-downloader/teasers/{POST_ID}.png'
PREVIOUS_TEASER = '.boosty-downloader/teasers/previous.jpg'
TEASER_THUMBNAIL_PATH = '.boosty-downloader/thumbs/teaser.png'


def _post(*, locked: bool = False) -> PostDTO:
    payload = synthetic_post()
    payload['hasAccess'] = not locked
    payload['data'] = [] if locked else [ok_video_chunk()]
    return PostDTO.model_validate(payload)


class _Transfers:
    def __init__(self) -> None:
        self.preview_calls: list[str] = []
        self.preview_reservations: list[frozenset[str]] = []
        self.teaser_urls: list[str] = []
        self.thumbnail_urls: list[str] = []
        self.error: BaseException | None = None

    async def preview(  # noqa: PLR0913 - mirrors the image adapter contract
        self,
        *,
        session: RetryClient,
        library_root: Path,
        post_folder: str,
        media_id: str,
        url: str,
        reserved_paths: Collection[str] = (),
    ) -> str:
        del session, url
        self.preview_calls.append(media_id)
        self.preview_reservations.append(frozenset(reserved_paths))
        if self.error is not None:
            raise self.error
        path = library_root / post_folder / PREVIEW_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'preview image')
        return PREVIEW_PATH

    async def teaser(
        self,
        *,
        session: RetryClient,
        library_root: Path,
        author: str,
        post_id: str,
        url: str,
    ) -> str:
        del session
        assert post_id == POST_ID
        self.teaser_urls.append(url)
        if self.error is not None:
            raise self.error
        path = library_root / author / TEASER_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'teaser image')
        return TEASER_PATH

    async def thumbnail(
        self,
        *,
        session: RetryClient,
        library_root: Path,
        author: str,
        post_id: str,
        url: str,
    ) -> str:
        del session
        assert post_id == POST_ID
        self.thumbnail_urls.append(url)
        if self.error is not None:
            raise self.error
        path = library_root / author / TEASER_THUMBNAIL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'teaser thumbnail')
        return TEASER_THUMBNAIL_PATH


@dataclass
class _Attempt:
    prepared: PreparedPost
    state: PostDownloadState


@dataclass
class _Run:
    context: DownloadContext
    store: JsonPostStore
    reporter: Mock
    transfers: _Transfers

    def prepare(self) -> _Attempt:
        prepared = PostPreparer(
            self.context.library_root, self.store, AUTHOR, BoostyOkVideoType.medium
        ).prepare(_post(), self.context.filters, datetime.now(timezone.utc))
        state = PostDownloadState(
            self.context.library_root, self.store, prepared, PostRunProgress()
        )
        if prepared.needs_update:
            state.save_initial()
        return _Attempt(prepared, state)

    async def previews(self, attempt: _Attempt) -> None:
        await preview_sync.ensure_post_previews(
            self.context, attempt.state, attempt.prepared
        )

    def saved(self) -> StoredPost:
        located = self.store.find_post(AUTHOR, POST_ID)
        assert located is not None
        assert located.record is not None
        return located.record

    def previous_teaser(self, *, on_disk: bool) -> LockedPost:
        observation = LockedPost(
            map_post_metadata(_post(locked=True), AUTHOR),
            datetime(2026, 1, 1, tzinfo=timezone.utc),
            teaser_path=PREVIOUS_TEASER,
        )
        self.store.save_locked_post(observation)
        if on_disk:
            path = self.context.library_root / AUTHOR / PREVIOUS_TEASER
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'previous teaser')
        return observation


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Run:
    store = JsonPostStore(tmp_path / 'library')
    reporter = Mock(spec=ProgressReporter)
    context = DownloadContext(
        author_name=AUTHOR,
        downloader_session=cast('RetryClient', None),
        external_videos_downloader=cast('ExternalVideosDownloader', None),
        post_store=store,
        library_root=tmp_path / 'library',
        filters=[],
        preferred_video_quality=BoostyOkVideoType.medium,
        progress_reporter=reporter,
        failed_logger=AsyncMock(spec=FailureLog),
    )
    transfers = _Transfers()
    monkeypatch.setattr(preview_sync, 'download_post_preview', transfers.preview)
    monkeypatch.setattr(post_access, 'download_locked_teaser', transfers.teaser)
    monkeypatch.setattr(
        thumbnail_sync, 'download_teaser_thumbnail', transfers.thumbnail
    )
    return _Run(context, store, reporter, transfers)


async def test_preview_is_saved_without_downloading_or_counting_its_video(
    run: _Run,
) -> None:
    attempt = run.prepare()
    before_stats = deepcopy(run.context.run_statistics)

    await run.previews(attempt)

    entry = run.saved().media[VIDEO_MEDIA_ID]
    assert entry.preview_path == PREVIEW_PATH
    assert entry.status is MediaStatus.pending
    assert entry.path is None
    assert entry.size is None
    assert run.context.run_statistics == before_stats
    assert run.transfers.preview_calls == [VIDEO_MEDIA_ID]
    assert (run.context.library_root / attempt.state.folder / PREVIEW_PATH).is_file()


async def test_prepared_retry_reuses_the_completed_preview(run: _Run) -> None:
    await run.previews(run.prepare())

    retry = run.prepare()
    await run.previews(retry)

    assert retry.prepared.preview_download_ids == ()
    assert run.transfers.preview_calls == [VIDEO_MEDIA_ID]
    assert run.saved().media[VIDEO_MEDIA_ID].preview_path == PREVIEW_PATH


async def test_preview_failure_warns_and_is_still_due_next_attempt(run: _Run) -> None:
    run.transfers.error = DownloadTimeoutError('https://images.example/preview')

    await run.previews(run.prepare())

    assert run.saved().media[VIDEO_MEDIA_ID].preview_path is None
    assert run.prepare().prepared.preview_download_ids == (VIDEO_MEDIA_ID,)
    run.reporter.warn.assert_called_once()


@pytest.mark.parametrize(
    'cancel', [CancelledError(), DownloadCancelledError('https://images.example')]
)
async def test_preview_cancellation_stops_the_post_without_becoming_a_warning(
    run: _Run,
    cancel: BaseException,
) -> None:
    run.transfers.error = cancel

    with pytest.raises(ApplicationCancelledError) as raised:
        await run.previews(run.prepare())

    assert raised.value.post_uuid == POST_ID
    assert raised.value.__cause__ is cancel
    run.reporter.warn.assert_not_called()


async def test_preview_record_failure_is_not_hidden_as_an_image_warning(
    run: _Run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempt = run.prepare()
    previous = deepcopy(attempt.state.record)

    def fail_save(_folder: str, _record: StoredPost) -> None:
        message = 'Preview record could not be saved'
        raise OSError(message)

    monkeypatch.setattr(run.store, 'save_post', fail_save)

    with pytest.raises(OSError, match='Preview record could not be saved'):
        await run.previews(attempt)

    assert attempt.state.record == previous
    assert run.saved() == previous
    assert (run.context.library_root / attempt.state.folder / PREVIEW_PATH).is_file()
    run.reporter.warn.assert_not_called()


async def test_locked_metadata_is_saved_before_its_signed_teaser(run: _Run) -> None:
    before_stats = deepcopy(run.context.run_statistics)

    await post_access.observe_post_access(run.context, _post(locked=True))

    saved = run.store.load_locked_post(AUTHOR, POST_ID)
    assert saved is not None
    assert saved.teaser_path == TEASER_PATH
    assert saved.teaser_thumbnail_path == TEASER_THUMBNAIL_PATH
    assert run.transfers.thumbnail_urls == run.transfers.teaser_urls
    assert run.transfers.teaser_urls == [
        f'https://images.example/teaser/{TEASER_ID}{SIGNED_QUERY}'
    ]
    assert run.store.find_post(AUTHOR, POST_ID) is None
    assert run.context.run_statistics == before_stats


@pytest.mark.parametrize('has_url', [False, True])
async def test_existing_teaser_is_reused_while_locked_metadata_changes(
    run: _Run,
    *,
    has_url: bool,
) -> None:
    run.previous_teaser(on_disk=True)
    post = _post(locked=True)
    post.title = 'Updated locked title'
    if not has_url:
        post.teaser = None

    await post_access.observe_post_access(run.context, post)

    saved = run.store.load_locked_post(AUTHOR, POST_ID)
    assert saved is not None
    assert saved.post.title == post.title
    assert saved.teaser_path == PREVIOUS_TEASER
    assert saved.teaser_thumbnail_path == (TEASER_THUMBNAIL_PATH if has_url else None)
    assert len(run.transfers.thumbnail_urls) == int(has_url)
    assert run.transfers.teaser_urls == []
    assert (
        run.context.library_root / AUTHOR / PREVIOUS_TEASER
    ).read_bytes() == b'previous teaser'


@pytest.mark.parametrize('has_url', [False, True])
async def test_missing_or_failed_teaser_keeps_previous_path_and_new_metadata(
    run: _Run,
    *,
    has_url: bool,
) -> None:
    run.previous_teaser(on_disk=False)
    run.transfers.error = DownloadTimeoutError('https://images.example/teaser')
    post = _post(locked=True)
    post.title = 'New locked overview'
    if not has_url:
        post.teaser = None

    await post_access.observe_post_access(run.context, post)

    saved = run.store.load_locked_post(AUTHOR, POST_ID)
    assert saved is not None
    assert saved.post.title == post.title
    assert saved.teaser_path == PREVIOUS_TEASER
    assert run.reporter.warn.call_count == int(has_url)


async def test_excluded_locked_post_records_metadata_without_fetching_teaser(
    run: _Run,
) -> None:
    run.context.excluded_tags = ('FIXTURE',)

    await post_access.observe_post_access(run.context, _post(locked=True))

    assert run.store.load_locked_post(AUTHOR, POST_ID) is not None
    assert run.transfers.teaser_urls == []


async def test_confirmed_access_clears_only_the_locked_observation(run: _Run) -> None:
    run.previous_teaser(on_disk=True)
    attempt = run.prepare()
    before = deepcopy(run.saved())

    await post_access.observe_post_access(run.context, _post())

    assert run.store.load_locked_post(AUTHOR, POST_ID) is None
    assert run.saved() == before == attempt.state.record
    assert (run.context.library_root / AUTHOR / PREVIOUS_TEASER).exists()
    assert run.transfers.teaser_urls == []


@pytest.mark.parametrize(
    'cancel', [CancelledError(), DownloadCancelledError('https://images.example')]
)
async def test_teaser_cancellation_preserves_the_observation_and_stops(
    run: _Run,
    cancel: BaseException,
) -> None:
    run.transfers.error = cancel

    with pytest.raises(ApplicationCancelledError) as raised:
        await post_access.observe_post_access(run.context, _post(locked=True))

    assert raised.value.__cause__ is cancel
    assert run.store.load_locked_post(AUTHOR, POST_ID) is not None
    run.reporter.warn.assert_not_called()


async def test_corrupt_observation_prevents_teaser_writes(
    run: _Run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load(_author: str, _post_id: str) -> LockedPost | None:
        message = 'Locked record belongs to another author'
        raise InvalidAuthorRecordError(message)

    monkeypatch.setattr(run.store, 'load_locked_post', fail_load)
    with pytest.raises(InvalidAuthorRecordError):
        await post_access.observe_post_access(run.context, _post(locked=True))

    assert run.transfers.teaser_urls == []
    assert not run.context.library_root.exists()


async def test_teaser_record_failure_preserves_new_metadata_and_propagates(
    run: _Run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run.previous_teaser(on_disk=False)
    save = run.store.save_locked_post

    def fail_image_save(observation: LockedPost) -> None:
        if observation.teaser_path == TEASER_PATH:
            message = 'Teaser record could not be saved'
            raise OSError(message)
        save(observation)

    monkeypatch.setattr(run.store, 'save_locked_post', fail_image_save)
    post = _post(locked=True)
    post.title = 'New locked overview'
    with pytest.raises(OSError, match='Teaser record could not be saved'):
        await post_access.observe_post_access(run.context, post)

    saved = run.store.load_locked_post(AUTHOR, POST_ID)
    assert saved is not None
    assert saved.post.title == post.title
    assert saved.teaser_path == PREVIOUS_TEASER
    assert (run.context.library_root / AUTHOR / TEASER_PATH).is_file()
    run.reporter.warn.assert_not_called()


async def test_teaser_cancellation_is_not_contained_as_a_post_failure(
    run: _Run,
) -> None:
    run.transfers.error = DownloadCancelledError('https://images.example')
    retrier = PostDownloadRetrier(
        author_name=AUTHOR,
        boosty_api=cast('BoostyAPIClient', None),
        destination=run.context.library_root / AUTHOR,
        download_context=run.context,
    )
    failed_posts: list[str] = []

    with pytest.raises(ApplicationCancelledError):
        await retrier.observe_access(_post(locked=True), failed_posts)

    assert failed_posts == []
    run.reporter.error.assert_not_called()
    run.reporter.warn.assert_not_called()


@pytest.mark.parametrize('path', ['../outside.png', '/outside.png'])
def test_preview_result_rejects_paths_outside_the_post(run: _Run, path: str) -> None:
    attempt = run.prepare()
    before = deepcopy(run.saved())

    with pytest.raises(ValueError, match='portable relative file path'):
        attempt.state.complete_preview(VIDEO_MEDIA_ID, path)

    assert run.saved() == before
    assert attempt.state.record == before


def test_unplanned_preview_cannot_change_a_record(run: _Run) -> None:
    attempt = run.prepare()
    before = deepcopy(run.saved())

    with pytest.raises(ValueError, match='not selected'):
        attempt.state.complete_preview('unexpected-media-id', PREVIEW_PATH)

    assert run.saved() == before
    assert attempt.state.record == before


async def test_failed_preview_retry_keeps_the_previous_path(run: _Run) -> None:
    attempt = run.prepare()
    record = run.saved()
    record.media[VIDEO_MEDIA_ID].preview_path = 'previews/previous.jpg'
    run.store.save_post(attempt.state.folder, record)
    run.transfers.error = DownloadTimeoutError('https://images.example/preview')

    await run.previews(run.prepare())

    assert run.saved().media[VIDEO_MEDIA_ID].preview_path == 'previews/previous.jpg'
    assert run.prepare().prepared.preview_download_ids == (VIDEO_MEDIA_ID,)


async def test_preview_transport_receives_all_other_retained_path_reservations(
    run: _Run,
) -> None:
    first = run.prepare()
    record = run.saved()
    video = record.media[VIDEO_MEDIA_ID]
    video.path = 'boosty_videos/main.mp4'
    video.preview_path = 'previews/missing-previous.png'
    record.media['boosty_video:removed-video'] = MediaEntry(
        kind=MediaKind.boosty_video,
        status=MediaStatus.deleted,
        added_at=video.added_at,
        removed_at=video.added_at,
        position=1,
        path='previews/retained-primary.png',
        preview_path='previews/retained-preview.png',
    )
    run.store.save_post(first.state.folder, record)

    await run.previews(run.prepare())

    assert run.transfers.preview_reservations == [
        frozenset(
            {
                'boosty_videos/main.mp4',
                'previews/retained-primary.png',
                'previews/retained-preview.png',
            }
        )
    ]


@pytest.mark.parametrize('content', [b'', None], ids=['empty', 'directory'])
def test_preview_completion_rejects_unusable_published_paths(
    run: _Run, content: bytes | None
) -> None:
    attempt = run.prepare()
    before = deepcopy(run.saved())
    path = run.context.library_root / attempt.state.folder / PREVIEW_PATH
    path.parent.mkdir(parents=True)
    if content is None:
        path.mkdir()
    else:
        path.write_bytes(content)

    with pytest.raises(ValueError, match='nonempty regular file'):
        attempt.state.complete_preview(VIDEO_MEDIA_ID, PREVIEW_PATH)

    assert run.saved() == before == attempt.state.record


def test_preview_completion_requires_an_existing_published_file(run: _Run) -> None:
    attempt = run.prepare()
    before = deepcopy(run.saved())

    with pytest.raises(FileNotFoundError):
        attempt.state.complete_preview(VIDEO_MEDIA_ID, PREVIEW_PATH)

    assert run.saved() == before == attempt.state.record
