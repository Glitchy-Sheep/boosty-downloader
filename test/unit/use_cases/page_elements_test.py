"""Published attachments feed the terminal complete page and run progress."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock, call
from uuid import uuid4

import pytest
from support.synthetic_post import FILE_ID, file_chunk, synthetic_post

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
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.media_publication import PublishedFile
from boosty_downloader.infrastructure.post_media_downloader import (
    MediaProgress,
    PostMediaDownloader,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aiohttp_retry import RetryClient

    from boosty_downloader.domain.post_data_chunks import PostDataChunkFile
    from boosty_downloader.domain.stored_post import StoredPost
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )
    from boosty_downloader.infrastructure.media_transfer import ReserveMediaPath
    from boosty_downloader.infrastructure.post_media_downloader import ProgressCallback

FILES = DownloadContentTypeFilter.files
POST_CONTENT = DownloadContentTypeFilter.post_content
ACTUAL_BYTES = b'report!'


async def _save_file(
    file: PostDataChunkFile, on_progress: ProgressCallback, *, reserve: ReserveMediaPath
) -> PublishedFile:
    target = reserve(file.filename)
    path = target.library_root / target.post_folder / target.relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ACTUAL_BYTES)
    on_progress(MediaProgress(downloaded_bytes=7, total_bytes=7, delta_bytes=7))
    return PublishedFile(path, size=len(ACTUAL_BYTES))


def _use_case(
    root: Path, filters: list[DownloadContentTypeFilter]
) -> DownloadSinglePostUseCase:
    payload = synthetic_post()
    payload['data'] = [{**file_chunk(), 'title': 'report.pdf', 'size': 4321}]
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
    downloader.download_file = AsyncMock(side_effect=_save_file)
    monkeypatch.setattr(
        use_case_module, 'PostMediaDownloader', Mock(return_value=downloader)
    )
    return downloader


def _record(use_case: DownloadSinglePostUseCase) -> StoredPost:
    located = use_case.context.post_store.find_post('author', use_case.post_dto.id)
    assert located is not None
    assert located.record is not None
    return located.record


@pytest.mark.parametrize(
    'filters', [[FILES, POST_CONTENT], [FILES]], ids=['with-images', 'files-only']
)
async def test_saved_attachment_appears_on_terminal_page_with_actual_size(
    tmp_path: Path, filters: list[DownloadContentTypeFilter], media: Mock
) -> None:
    use_case = _use_case(tmp_path, filters)

    await use_case.execute()

    entry = _record(use_case).media[f'file:{FILE_ID}']
    media.download_file.assert_awaited_once()
    assert entry.status is MediaStatus.downloaded
    assert entry.size == len(ACTUAL_BYTES)
    assert not (use_case.destination / 'post.html').exists()
    assert _record(use_case).sync.page_template is None
    use_case.finalize()
    page = (use_case.destination / 'post.html').read_text(encoding='utf-8')
    assert 'href="files/report.pdf"' in page
    assert '7 B' in page
    assert _record(use_case).sync.page_template == PAGE_TEMPLATE_VERSION
    assert use_case.context.run_statistics.media.files == 1
    assert use_case.context.run_statistics.downloaded_bytes == len(ACTUAL_BYTES)
    assert use_case.context.run_statistics.posts_downloaded == 0
    use_case.record_success()
    assert use_case.context.run_statistics.posts_downloaded == 1


async def test_media_progress_is_forwarded_and_all_tasks_are_completed(
    tmp_path: Path,
    media: Mock,
) -> None:
    use_case = _use_case(tmp_path, [FILES])
    reporter = cast('Mock', use_case.context.progress_reporter)
    post_task, media_task = uuid4(), uuid4()
    reporter.create_task.side_effect = [post_task, media_task]

    await use_case.execute()
    assert reporter.create_task.call_args_list == [
        call(f'[bold]POST: {use_case.post_dto.title}[/bold]', total=1, indent_level=1),
        call('File: report.pdf', total=4321, indent_level=2),
    ]
    assert reporter.update_task.call_args_list == [
        call(
            media_task,
            advance=7,
            total=7,
            description='File: report.pdf [7.00 B / 7.00 B]',
        ),
        call(post_task, advance=1),
    ]
    assert reporter.complete_task.call_args_list == [call(media_task), call(post_task)]
    media.download_file.assert_awaited_once()


async def test_finalize_is_idempotent_and_later_unchanged_run_keeps_page(
    tmp_path: Path,
    media: Mock,
) -> None:
    use_case = _use_case(tmp_path, [FILES])
    await use_case.execute()
    use_case.finalize()
    page = use_case.destination / 'post.html'
    saved_page = page.read_bytes()
    saved_modified_ns = page.stat().st_mtime_ns

    use_case.finalize()
    second = _use_case(tmp_path, [FILES])
    await second.execute()
    second.finalize()
    second.record_success()

    assert page.read_bytes() == saved_page
    assert page.stat().st_mtime_ns == saved_modified_ns
    media.download_file.assert_awaited_once()
    assert second.context.run_statistics.posts_cached == 1
    assert second.context.run_statistics.posts_downloaded == 0
    assert second.context.run_statistics.downloaded_bytes == 0
