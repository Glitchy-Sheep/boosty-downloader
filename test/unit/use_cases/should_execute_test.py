"""Filters select media transfers while every accessible post keeps its full page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
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

from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.ports import FailureLog, ProgressReporter
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


@dataclass(frozen=True, slots=True)
class MediaCase:
    payload: dict[str, object]
    selected_filter: DownloadContentTypeFilter
    method: str


MEDIA_CASES = [
    MediaCase(file_chunk(), DownloadContentTypeFilter.files, 'download_file'),
    MediaCase(audio_chunk(), DownloadContentTypeFilter.audio, 'download_audio'),
    MediaCase(
        ok_video_chunk(),
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
) -> DownloadSinglePostUseCase:
    payload = synthetic_post()
    payload['data'] = chunks
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
    tmp_path: Path, case: MediaCase, selected: DownloadContentTypeFilter, media: Mock
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
    page = (use_case.destination / 'post.html').read_text()
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
    page = (second.destination / 'post.html').read_text()
    assert 'href="files/saved.bin"' in page
    assert 'src="audio/saved.bin"' in page


@pytest.mark.parametrize(
    'chunk',
    [file_chunk(), audio_chunk(), ok_video_chunk()],
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
    assert 'not downloaded' in (use_case.destination / 'post.html').read_text()


@pytest.mark.parametrize(
    'title', ['Stream lesson', '   '], ids=['named', 'blank-title']
)
async def test_stream_only_video_warns_with_display_title_without_download(
    tmp_path: Path, title: str, media: Mock
) -> None:
    chunk: dict[str, object] = {
        **ok_video_chunk(),
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
    assert 'not downloaded' in (use_case.destination / 'post.html').read_text()
