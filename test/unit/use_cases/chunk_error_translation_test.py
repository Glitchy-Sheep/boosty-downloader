"""Media failures persist per piece and reach the retrier without losing causes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import pytest
from support.synthetic_post import FILE_ID, POST_ID, file_chunk, synthetic_post

from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.ports import FailureLog, ProgressReporter
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.file_downloader import (
    DownloadUnexpectedStatusError,
    is_expired_link_error,
)
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.post_media_downloader import (
    MediaDownloadError,
    PostMediaDownloader,
)

if TYPE_CHECKING:
    from aiohttp_retry import RetryClient

    from boosty_downloader.domain.stored_post import MediaEntry
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )

RESOURCE = 'https://cdn.example/file'


def _use_case(root: Path, error: BaseException) -> DownloadSinglePostUseCase:
    payload = synthetic_post()
    payload['data'] = [{**file_chunk(), 'url': RESOURCE}]
    reporter = Mock(spec=ProgressReporter)
    reporter.create_task.return_value = uuid4()
    context = DownloadContext(
        author_name='author',
        downloader_session=cast('RetryClient', None),
        external_videos_downloader=cast('ExternalVideosDownloader', None),
        post_store=JsonPostStore(root),
        library_root=root,
        filters=[DownloadContentTypeFilter.files],
        preferred_video_quality=BoostyOkVideoType.medium,
        progress_reporter=reporter,
        failed_logger=AsyncMock(spec=FailureLog),
    )
    media = Mock(spec=PostMediaDownloader)
    media.download_file = AsyncMock(side_effect=error)
    with patch(
        'boosty_downloader.application.use_cases.download_single_post.PostMediaDownloader',
        return_value=media,
    ):
        return DownloadSinglePostUseCase(root, PostDTO.model_validate(payload), context)


def _entry(use_case: DownloadSinglePostUseCase) -> MediaEntry:
    located = use_case.context.post_store.find_post('author', POST_ID)
    assert located is not None
    assert located.record is not None
    return located.record.media[f'file:{FILE_ID}']


@pytest.mark.parametrize(
    'file', [Path('files/a.zip'), None], ids=['with-file', 'without-file']
)
async def test_media_error_is_saved_logged_and_translated(
    tmp_path: Path, file: Path | None
) -> None:
    media_error = MediaDownloadError('gone', resource_url=RESOURCE, file=file)
    use_case = _use_case(tmp_path, media_error)

    with pytest.raises(ApplicationFailedDownloadError) as info:
        await use_case.execute()

    assert info.value.post_uuid == POST_ID
    assert info.value.resource == RESOURCE
    assert 'gone' in info.value.message
    assert info.value.__cause__ is media_error
    logger = cast('AsyncMock', use_case.context.failed_logger)
    logger.add_error.assert_awaited_once_with(
        f'https://boosty.to/author/posts/{POST_ID} - {RESOURCE}', 'gone'
    )
    entry = _entry(use_case)
    assert entry.status is MediaStatus.failed
    assert entry.error == 'gone'


@pytest.mark.parametrize('retryable', [True, False], ids=['retryable', 'gone'])
async def test_retry_flag_controls_the_application_error_and_saved_status(
    tmp_path: Path, *, retryable: bool
) -> None:
    use_case = _use_case(
        tmp_path,
        MediaDownloadError('gone', resource_url=RESOURCE, retryable=retryable),
    )

    with pytest.raises(ApplicationFailedDownloadError) as info:
        await use_case.execute()

    assert info.value.retryable is retryable
    expected = MediaStatus.failed if retryable else MediaStatus.unavailable
    assert _entry(use_case).status is expected
    assert (
        f'file:{FILE_ID}' in use_case.run_progress.checked_unavailable_ids
    ) is not retryable


async def test_expired_link_stays_detectable_through_cause_chain(
    tmp_path: Path,
) -> None:
    expired = DownloadUnexpectedStatusError(
        status=400, response_message='Bad Request', resource_url=RESOURCE
    )
    media_error = MediaDownloadError(expired.message, resource_url=RESOURCE)
    media_error.__cause__ = expired
    use_case = _use_case(tmp_path, media_error)

    with pytest.raises(ApplicationFailedDownloadError) as info:
        await use_case.execute()

    assert is_expired_link_error(info.value)
    assert _entry(use_case).status is MediaStatus.failed


async def test_cancellation_is_neither_logged_nor_recorded_as_media_failure(
    tmp_path: Path,
) -> None:
    use_case = _use_case(tmp_path, asyncio.CancelledError())

    with pytest.raises(ApplicationCancelledError):
        await use_case.execute()

    cast('AsyncMock', use_case.context.failed_logger).add_error.assert_not_awaited()
    entry = _entry(use_case)
    assert entry.status is MediaStatus.pending
    assert entry.error is None


async def test_failure_log_error_keeps_original_media_error_and_saved_outcome(
    tmp_path: Path,
) -> None:
    media_error = MediaDownloadError('gone', RESOURCE, retryable=False)
    use_case = _use_case(tmp_path, media_error)
    cast('AsyncMock', use_case.context.failed_logger).add_error.side_effect = OSError(
        'log denied'
    )

    with pytest.raises(ApplicationFailedDownloadError) as info:
        await use_case.execute()

    assert info.value.__cause__ is media_error
    assert not info.value.retryable
    assert _entry(use_case).status is MediaStatus.unavailable
    cast('Mock', use_case.context.progress_reporter).warn.assert_called_once_with(
        'Could not write failure log: log denied'
    )
