"""Filters select media transfers while every accessible post keeps its full page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from support.raster_images import png_bytes
from support.synthetic_post import (
    AUDIO_ID,
    FILE_ID,
    audio_chunk,
    file_chunk,
    image_chunk,
    ok_video_chunk,
    synthetic_post,
    text_chunk,
)

from boosty_downloader.application import thumbnail_sync
from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.ports import FailureLog, ProgressReporter
from boosty_downloader.application.post_download_state import PostRunProgress
from boosty_downloader.application.use_cases import (
    download_single_post as use_case_module,
)
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.media_publication import PublishedFile
from boosty_downloader.infrastructure.post_media_downloader import PostMediaDownloader

if TYPE_CHECKING:
    from pathlib import Path

    from aiohttp_retry import RetryClient

    from boosty_downloader.domain.stored_post import StoredPost
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )
    from boosty_downloader.infrastructure.media_transfer import ReserveMediaPath
    from boosty_downloader.infrastructure.post_media_downloader import ProgressCallback


THUMBNAIL_PATH = '.boosty-downloader/thumbs/image.png'


@pytest.fixture
def thumbnail(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    async def publish(*, library_root: Path, author: str, **_kwargs: object) -> str:
        path = library_root / author / THUMBNAIL_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes())
        return THUMBNAIL_PATH

    download = AsyncMock(side_effect=publish)
    monkeypatch.setattr(thumbnail_sync, 'download_post_thumbnail', download)
    return download


@dataclass(frozen=True, slots=True)
class MediaCase:
    payload: dict[str, object]
    selected_filter: DownloadContentTypeFilter
    method: str


def _video_chunk() -> dict[str, object]:
    return {**ok_video_chunk(), 'preview': ''}


MEDIA_CASES = [
    MediaCase(file_chunk(), DownloadContentTypeFilter.files, 'download_file'),
    MediaCase(audio_chunk(), DownloadContentTypeFilter.audio, 'download_audio'),
    MediaCase(
        _video_chunk(),
        DownloadContentTypeFilter.boosty_videos,
        'download_boosty_video',
    ),
    MediaCase(
        {'type': 'video', 'url': 'https://www.youtube.com/watch?v=fixture'},
        DownloadContentTypeFilter.external_videos,
        'download_external_video',
    ),
    MediaCase(image_chunk(), DownloadContentTypeFilter.post_content, 'download_image'),
]


async def _download(
    chunk: object, on_progress: ProgressCallback, *, reserve: ReserveMediaPath
) -> PublishedFile:
    del chunk, on_progress
    target = reserve('saved.bin')
    path = target.library_root / target.post_folder / target.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x')
    return PublishedFile(path, size=1)


def _use_case(
    root: Path,
    chunks: list[dict[str, object]],
    filters: list[DownloadContentTypeFilter],
    *,
    restore_missing: bool = False,
) -> DownloadSinglePostUseCase:
    payload = synthetic_post()
    payload['data'] = chunks
    payload['teaser'] = []
    reporter = Mock(spec=ProgressReporter)
    reporter.create_task.return_value = uuid4()
    context = DownloadContext(
        author_name='author',
        downloader_session=cast('RetryClient', None),
        external_videos_downloader=cast('ExternalVideosDownloader', None),
        post_store=JsonPostStore(root),
        library_root=root,
        filters=filters,
        preferred_video_quality=BoostyOkVideoType.medium,
        progress_reporter=reporter,
        failed_logger=AsyncMock(spec=FailureLog),
        restore_missing=restore_missing,
    )
    return DownloadSinglePostUseCase(root, PostDTO.model_validate(payload), context)


@pytest.fixture
def media(monkeypatch: pytest.MonkeyPatch) -> Mock:
    downloader = Mock(spec=PostMediaDownloader)
    for case in MEDIA_CASES:
        setattr(downloader, case.method, AsyncMock(side_effect=_download))
    monkeypatch.setattr(
        use_case_module, 'PostMediaDownloader', Mock(return_value=downloader)
    )
    return downloader


def _record(use_case: DownloadSinglePostUseCase) -> StoredPost:
    located = use_case.context.post_store.find_post('author', use_case.post_dto.id)
    assert located is not None
    assert located.record is not None
    return located.record


@pytest.mark.parametrize('case', MEDIA_CASES, ids=lambda case: case.method)
@pytest.mark.parametrize('selected', list(DownloadContentTypeFilter))
async def test_each_media_kind_downloads_only_under_its_filter(
    tmp_path: Path,
    case: MediaCase,
    selected: DownloadContentTypeFilter,
    media: Mock,
    thumbnail: AsyncMock,
) -> None:
    use_case = _use_case(tmp_path, [case.payload], [selected])

    await use_case.execute()
    use_case.finalize()

    selected_method = getattr(media, case.method)
    if selected is case.selected_filter:
        selected_method.assert_awaited_once()
        assert (
            next(iter(_record(use_case).media.values())).status
            is MediaStatus.downloaded
        )
    else:
        selected_method.assert_not_awaited()
        assert (
            next(iter(_record(use_case).media.values())).status is MediaStatus.pending
        )
    for other in MEDIA_CASES:
        if other.method != case.method:
            getattr(media, other.method).assert_not_awaited()
    entry = next(iter(_record(use_case).media.values()))
    if case.method == 'download_image' and selected is case.selected_filter:
        thumbnail.assert_awaited_once()
        assert entry.thumbnail_path == THUMBNAIL_PATH
        assert (tmp_path / 'author' / THUMBNAIL_PATH).read_bytes() == png_bytes()
        assert use_case.context.run_statistics.downloaded_bytes == 1
    else:
        thumbnail.assert_not_awaited()
        assert entry.thumbnail_path is None
    assert (use_case.destination / 'post.html').is_file()


@pytest.mark.parametrize(
    'chunks',
    [
        [],
        [text_chunk('Readable text')],
        [{'type': 'list', 'items': [{'data': [text_chunk('List item')]}]}],
    ],
    ids=['empty', 'text', 'list'],
)
@pytest.mark.parametrize(
    'filters', [[], [DownloadContentTypeFilter.files]], ids=['none', 'files']
)
async def test_posts_without_selected_media_still_save_complete_body_and_page(
    tmp_path: Path,
    chunks: list[dict[str, object]],
    filters: list[DownloadContentTypeFilter],
    media: Mock,
) -> None:
    use_case = _use_case(tmp_path, chunks, filters)

    await use_case.execute()
    use_case.finalize()

    record = _record(use_case)
    assert not record.media
    assert bool(record.blocks) is bool(chunks)
    page = (use_case.destination / 'post.html').read_text(encoding='utf-8')
    if chunks:
        assert 'Readable text' in page or 'List item' in page
    assert media.mock_calls == []


async def test_no_selected_filters_keeps_pending_media_without_downloading(
    tmp_path: Path,
    media: Mock,
) -> None:
    use_case = _use_case(tmp_path, [file_chunk()], [])

    await use_case.execute()
    use_case.finalize()

    media.download_file.assert_not_awaited()
    assert _record(use_case).media[f'file:{FILE_ID}'].status is MediaStatus.pending
    assert (use_case.destination / 'post.html').is_file()


async def test_later_audio_filter_adds_audio_without_redownloading_saved_file(
    tmp_path: Path,
    media: Mock,
) -> None:
    chunks = [file_chunk(), audio_chunk()]
    first = _use_case(tmp_path, chunks, [DownloadContentTypeFilter.files])
    await first.execute()
    first.finalize()
    file_path = _record(first).media[f'file:{FILE_ID}'].path

    second = _use_case(tmp_path, chunks, [DownloadContentTypeFilter.audio])
    await second.execute()
    second.finalize()

    media.download_file.assert_awaited_once()
    media.download_audio.assert_awaited_once()
    record = _record(second)
    assert record.media[f'file:{FILE_ID}'].status is MediaStatus.downloaded
    assert record.media[f'file:{FILE_ID}'].path == file_path
    assert record.media[f'audio:{AUDIO_ID}'].status is MediaStatus.downloaded
    page = (second.destination / 'post.html').read_text(encoding='utf-8')
    assert 'href="files/saved.bin"' in page
    assert 'src="audio/saved.bin"' in page


@pytest.mark.parametrize(
    'chunk',
    [file_chunk(), audio_chunk(), _video_chunk()],
    ids=['file', 'audio', 'video'],
)
async def test_unfinished_upload_warns_and_keeps_a_pending_placeholder(
    tmp_path: Path, chunk: dict[str, object], media: Mock
) -> None:
    use_case = _use_case(
        tmp_path, [{**chunk, 'complete': False}], list(DownloadContentTypeFilter)
    )

    await use_case.execute()
    use_case.finalize()

    assert media.mock_calls == []
    cast('Mock', use_case.context.progress_reporter).warn.assert_called_once_with(
        'Post has unfinished uploads (will retry next run): '
        + use_case.destination.name
    )
    assert next(iter(_record(use_case).media.values())).status is MediaStatus.pending
    assert 'not downloaded' in (use_case.destination / 'post.html').read_text(
        encoding='utf-8'
    )


@pytest.mark.parametrize(
    'title', ['Stream lesson', '   '], ids=['named', 'blank-title']
)
async def test_stream_only_video_warns_with_display_title_without_download(
    tmp_path: Path, title: str, media: Mock
) -> None:
    chunk: dict[str, object] = {
        **_video_chunk(),
        'title': title,
        'playerUrls': [{'type': 'hls', 'url': 'https://video.example/stream.m3u8'}],
    }
    use_case = _use_case(tmp_path, [chunk], list(DownloadContentTypeFilter))

    await use_case.execute()
    use_case.finalize()

    assert media.mock_calls == []
    reporter = cast('Mock', use_case.context.progress_reporter)
    reporter.warn.assert_any_call(
        'Skip video (streams are not supported yet): ' + (title.strip() or 'video')
    )
    assert next(iter(_record(use_case).media.values())).status is MediaStatus.pending
    assert 'not downloaded' in (use_case.destination / 'post.html').read_text(
        encoding='utf-8'
    )


async def _save_then_delete_media(
    root: Path, chunks: list[dict[str, object]]
) -> DownloadSinglePostUseCase:
    use_case = _use_case(root, chunks, list(DownloadContentTypeFilter))
    await use_case.execute()
    use_case.finalize()
    for entry in _record(use_case).media.values():
        assert entry.path is not None
        (use_case.destination / entry.path).unlink()
    return use_case


@pytest.mark.parametrize('restore_missing', [False, True])
async def test_deleted_media_is_restored_only_when_requested_and_selected(
    tmp_path: Path, media: Mock, *, restore_missing: bool
) -> None:
    chunks = [file_chunk(), audio_chunk()]
    await _save_then_delete_media(tmp_path, chunks)
    media.reset_mock()
    use_case = _use_case(
        tmp_path,
        chunks,
        [DownloadContentTypeFilter.files],
        restore_missing=restore_missing,
    )

    await use_case.execute()
    use_case.finalize()

    assert media.download_file.await_count == int(restore_missing)
    media.download_audio.assert_not_awaited()
    assert use_case.context.run_statistics.media_deleted == (
        1 if restore_missing else 2
    )
    record = _record(use_case)
    expected_file_status = (
        MediaStatus.downloaded if restore_missing else MediaStatus.deleted
    )
    assert record.media[f'file:{FILE_ID}'].status is expected_file_status
    assert record.media[f'audio:{AUDIO_ID}'].status is MediaStatus.deleted


async def test_deleted_count_is_preserved_on_unchanged_retries_and_replaced_on_refresh(
    tmp_path: Path, media: Mock
) -> None:
    chunks = [file_chunk(), audio_chunk()]
    await _save_then_delete_media(tmp_path, chunks)
    media.reset_mock()
    use_case = _use_case(tmp_path, chunks, [])
    assert use_case.context.restore_missing is False
    await use_case.execute()
    use_case.finalize()
    assert use_case.context.run_statistics.media_deleted == 2

    retry = DownloadSinglePostUseCase(
        tmp_path,
        use_case.post_dto,
        use_case.context,
        run_progress=use_case.run_progress,
    )
    await retry.execute()
    retry.finalize()
    retry.record_success()
    assert use_case.context.run_statistics.media_deleted == 2
    assert use_case.context.run_statistics.posts_cached == 1

    payload = synthetic_post()
    payload['data'] = [audio_chunk()]
    refreshed = DownloadSinglePostUseCase(
        tmp_path,
        PostDTO.model_validate(payload),
        use_case.context,
        run_progress=use_case.run_progress,
    )
    await refreshed.execute()
    refreshed.finalize()

    assert use_case.context.run_statistics.media_deleted == 1
    assert media.mock_calls == []
    assert _record(refreshed).media[f'file:{FILE_ID}'].removed_at is not None


async def test_failed_peer_does_not_hide_or_duplicate_deleted_media(
    tmp_path: Path, media: Mock
) -> None:
    await _save_then_delete_media(tmp_path, [audio_chunk()])
    use_case = _use_case(
        tmp_path, [audio_chunk(), file_chunk()], [DownloadContentTypeFilter.files]
    )
    media.download_file.side_effect = OSError('disk failure')
    for _ in range(2):
        with pytest.raises(OSError, match='disk failure'):
            await use_case.execute()
        assert use_case.context.run_statistics.media_deleted == 1


async def test_deleted_counts_add_for_independent_posts_in_the_same_run(
    tmp_path: Path, media: Mock
) -> None:
    first = await _save_then_delete_media(tmp_path, [file_chunk()])
    payload = synthetic_post()
    payload.update(id='90000000-0000-4000-8000-000000000001', data=[file_chunk()])
    post = PostDTO.model_validate(payload)
    other = DownloadSinglePostUseCase(tmp_path, post, first.context)
    await other.execute()
    other.finalize()
    located = first.context.post_store.find_post('author', post.id)
    assert located is not None
    assert located.record is not None
    entry = located.record.media[f'file:{FILE_ID}']
    assert entry.path is not None
    (tmp_path / located.folder / entry.path).unlink()
    media.reset_mock()
    use_case = _use_case(tmp_path, [file_chunk()], [])
    await use_case.execute()
    assert use_case.context.run_statistics.media_deleted == 1
    second = DownloadSinglePostUseCase(
        tmp_path, post, use_case.context, run_progress=PostRunProgress()
    )
    await second.execute()

    assert use_case.context.run_statistics.media_deleted == 2
    assert media.mock_calls == []
