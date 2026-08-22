"""Post media downloads run in parallel - capped, ordered, same error contract."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID, uuid4

import pytest

from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.filtering import (
    BoostyOkVideoType,
    DownloadContentTypeFilter,
)
from boosty_downloader.application.use_cases import (
    download_single_post as usecase_module,
)
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.di.download_context import DownloadContext
    from boosty_downloader.domain.post import PostDataAllChunks
    from boosty_downloader.domain.post_data_chunks import PostDataChunkFile
    from boosty_downloader.infrastructure.html_generator.models import HtmlGenChunk

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


class _FakeReporter:
    def create_task(self, *args: object, **kwargs: object) -> UUID:
        del args, kwargs
        return uuid4()

    def update_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def complete_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def success(self, message: str) -> None:
        del message

    def notice(self, message: str) -> None:
        del message

    def warn(self, message: str) -> None:
        del message


class _FakeCache:
    def get_post_missing_parts(
        self, **kwargs: object
    ) -> list[DownloadContentTypeFilter]:
        del kwargs
        return [DownloadContentTypeFilter.files, DownloadContentTypeFilter.post_content]

    def cache_post(self, *args: object) -> None:
        del args

    def commit(self) -> None:
        pass


class _Context:
    def __init__(self) -> None:
        self.progress_reporter = _FakeReporter()
        self.post_cache = _FakeCache()
        self.filters = [
            DownloadContentTypeFilter.files,
            DownloadContentTypeFilter.post_content,
        ]
        self.preferred_video_quality = BoostyOkVideoType.medium


def _post_dto(file_count: int) -> PostDTO:
    return PostDTO(
        id='p1',
        title='parallel post',
        created_at=NOW,
        updated_at=NOW,
        has_access=True,
        signed_query='',
        data=[
            {
                'type': 'file',
                'id': f'f{n}',
                'url': f'https://cdn/f{n}',
                'title': f'file-{n}.bin',
                'size': 1,
                'complete': True,
            }
            for n in range(file_count)
        ],
    )


def _use_case(tmp_path: Path, file_count: int) -> DownloadSinglePostUseCase:
    return DownloadSinglePostUseCase(
        destination=tmp_path / 'post',
        post_dto=_post_dto(file_count),
        download_context=cast('DownloadContext', _Context()),
    )


async def test_chunks_download_in_parallel_capped_and_ordered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Six 50ms chunks must overlap (but never more than 4 at once) and the
    rendered page must keep the author's chunk order regardless of finish order.
    """
    active = 0
    max_active = 0

    async def scripted(
        self: DownloadSinglePostUseCase,
        chunk: PostDataAllChunks,
        missing: object,
        post: object,
    ) -> object:
        del self, missing, post
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return cast('PostDataChunkFile', chunk).filename

    rendered: list[list[str]] = []

    def fake_render(chunks: list[HtmlGenChunk], **kwargs: object) -> None:
        del kwargs
        rendered.append(cast('list[str]', chunks))

    monkeypatch.setattr(DownloadSinglePostUseCase, '_safely_process_chunk', scripted)
    monkeypatch.setattr(usecase_module, 'render_html_to_file', fake_render)

    started = time.monotonic()
    await _use_case(tmp_path, 6).execute()
    duration = time.monotonic() - started

    assert max_active <= 4, 'the semaphore must cap concurrency at 4'
    assert max_active >= 2, 'chunks must actually overlap'
    assert duration < 0.25, f'6x50ms must not run sequentially (took {duration:.2f}s)'
    assert rendered == [[f'file-{n}.bin' for n in range(6)]], (
        'the page must keep the original chunk order'
    )


async def test_one_failed_chunk_raises_the_original_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Sibling cancellation must not mask the real failure as a user cancel."""

    async def scripted(
        self: DownloadSinglePostUseCase,
        chunk: PostDataAllChunks,
        missing: object,
        post: object,
    ) -> object:
        del self, missing, post
        name = cast('PostDataChunkFile', chunk).filename
        if name == 'file-1.bin':
            await asyncio.sleep(0.01)
            raise ApplicationFailedDownloadError(
                post_uuid='p1', message='dead link', resource=name
            )
        await asyncio.sleep(0.2)
        return name

    monkeypatch.setattr(DownloadSinglePostUseCase, '_safely_process_chunk', scripted)

    with pytest.raises(ApplicationFailedDownloadError):
        await _use_case(tmp_path, 4).execute()


async def test_outer_cancel_keeps_the_application_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Ctrl+C during a parallel batch must still surface as the application
    cancellation (the 130 exit code depends on it), not a bare CancelledError.
    """

    async def scripted(*args: Any, **kwargs: Any) -> object:  # noqa: ANN401
        del args, kwargs
        await asyncio.sleep(5)
        return None

    monkeypatch.setattr(DownloadSinglePostUseCase, '_safely_process_chunk', scripted)

    task = asyncio.create_task(_use_case(tmp_path, 3).execute())
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(ApplicationCancelledError):
        await task
