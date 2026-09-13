"""A failed media download must become an application error, never a traceback.

The media downloader is faked; the use case's translation is real: the
failure lands in failed_downloads.log, the retrier gets a typed error,
cancellation keeps its own type.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post import Post
from boosty_downloader.domain.post_data_chunks import PostDataChunkFile
from boosty_downloader.infrastructure.file_downloader import (
    DownloadUnexpectedStatusError,
    is_expired_link_error,
)
from boosty_downloader.infrastructure.post_media_downloader import (
    MediaDownloadError,
)

if TYPE_CHECKING:
    from uuid import UUID

    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
    from boosty_downloader.infrastructure.post_media_downloader import (
        PostMediaDownloader,
        ProgressCallback,
    )

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
RESOURCE = 'https://cdn.example/file'


class _FakeFailedLogger:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    async def add_error(self, error_id: str, message: str) -> None:
        self.entries.append((error_id, message))


class _QuietReporter:
    def create_task(self, *args: object, **kwargs: object) -> UUID:
        del args, kwargs
        from uuid import uuid4  # noqa: PLC0415 - keeps the fake to its one job

        return uuid4()

    def update_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def complete_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs


class _Context:
    """Only the fields the chunk path touches."""

    def __init__(self) -> None:
        self.author_name = 'author'
        self.failed_logger = _FakeFailedLogger()
        self.progress_reporter = _QuietReporter()


class _FailingMedia:
    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def download_file(
        self, file: PostDataChunkFile, on_progress: ProgressCallback
    ) -> Path:
        del file, on_progress
        raise self._error


def _post() -> Post:
    return Post(
        uuid='p1',
        title='post',
        created_at=NOW,
        updated_at=NOW,
        has_access=True,
        signed_query='',
        post_data_chunks=[],
    )


def _use_case(media: _FailingMedia) -> tuple[DownloadSinglePostUseCase, _Context]:
    context = _Context()
    use_case = DownloadSinglePostUseCase(
        destination=Path('unused'),
        post_dto=cast('PostDTO', None),
        download_context=cast('DownloadContext', context),
    )
    # cached_property: the instance value wins over the lazily built downloader.
    use_case._media = cast('PostMediaDownloader', media)
    return use_case, context


async def _process_file_chunk(use_case: DownloadSinglePostUseCase) -> None:
    await use_case._safely_process_chunk(
        PostDataChunkFile(url=RESOURCE, filename='a.zip'),
        [DownloadContentTypeFilter.files],
        _post(),
    )


@pytest.mark.parametrize(
    ('file', 'expected_resource'),
    [(Path('files/a.zip'), 'a.zip'), (None, RESOURCE)],
    ids=['with-file', 'without-file'],
)
async def test_media_error_becomes_an_application_error_and_is_logged(
    file: Path | None, expected_resource: str
) -> None:
    """The retrier decides on typed errors; the log tells the user what and why."""
    use_case, context = _use_case(
        _FailingMedia(MediaDownloadError('gone', resource_url=RESOURCE, file=file))
    )

    with pytest.raises(ApplicationFailedDownloadError) as info:
        await _process_file_chunk(use_case)

    assert info.value.post_uuid == 'p1'
    assert info.value.resource == expected_resource
    assert 'gone' in info.value.message
    assert context.failed_logger.entries == [
        (
            f'https://boosty.to/author/posts/p1 - {RESOURCE}',
            f'Failed to download {expected_resource}: gone',
        )
    ]


async def test_expired_link_stays_detectable_through_the_cause_chain() -> None:
    """The retrier refreshes the post only if it can still see the 400 underneath."""
    expired = DownloadUnexpectedStatusError(
        status=400, response_message='Bad Request', resource_url=RESOURCE
    )
    media_error = MediaDownloadError(expired.message, resource_url=RESOURCE)
    media_error.__cause__ = expired
    use_case, _ = _use_case(_FailingMedia(media_error))

    with pytest.raises(ApplicationFailedDownloadError) as info:
        await _process_file_chunk(use_case)

    assert is_expired_link_error(info.value)


async def test_cancellation_keeps_its_own_type() -> None:
    """Ctrl+C must not be reported as a failed download: the 130 exit code depends on it."""
    use_case, context = _use_case(_FailingMedia(asyncio.CancelledError()))

    with pytest.raises(ApplicationCancelledError):
        await _process_file_chunk(use_case)

    assert context.failed_logger.entries == []
