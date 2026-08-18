"""A failed external video must become an application error, never a traceback."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from boosty_downloader.src.application.exceptions.application_errors import (
    ApplicationFailedDownloadError,
)
from boosty_downloader.src.application.filtering import DownloadContentTypeFilter
from boosty_downloader.src.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.src.domain.post import Post
from boosty_downloader.src.domain.post_data_chunks import PostDataChunkExternalVideo
from boosty_downloader.src.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExtVideoDownloadError,
    ExtVideoError,
    ExtVideoInfoError,
)

if TYPE_CHECKING:
    from boosty_downloader.src.application.di.download_context import DownloadContext
    from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeFailedLogger:
    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    async def add_error(self, error_id: str, message: str) -> None:
        self.entries.append((error_id, message))


class _Context:
    """Only the fields the error-translation path touches."""

    def __init__(self) -> None:
        self.author_name = 'author'
        self.failed_logger = _FakeFailedLogger()


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


@pytest.mark.parametrize(
    'error',
    [
        ExtVideoError('https://youtube/watch'),
        ExtVideoError(),
        ExtVideoDownloadError('https://youtube/watch'),
        ExtVideoInfoError('https://youtube/watch'),
    ],
    ids=['base', 'base-without-url', 'download', 'info'],
)
async def test_every_ext_video_error_becomes_an_application_error(
    monkeypatch: pytest.MonkeyPatch, error: ExtVideoError
) -> None:
    """The wrapper used to raise the bare base class past the translation tower:
    a removed or restricted video crashed --post-url with a raw traceback.
    """
    context = _Context()
    use_case = DownloadSinglePostUseCase(
        destination=Path('unused'),
        post_dto=cast('PostDTO', None),
        download_context=cast('DownloadContext', context),
    )

    async def failing_download(**kwargs: object) -> Path:
        del kwargs
        raise error

    monkeypatch.setattr(use_case, 'download_external_videos', failing_download)

    with pytest.raises(ApplicationFailedDownloadError):
        await use_case._safely_process_chunk(
            PostDataChunkExternalVideo(url='https://youtube/watch'),
            [DownloadContentTypeFilter.external_videos],
            _post(),
        )

    assert context.failed_logger.entries, 'the failure must land in the failed log'
