"""Post media downloads run in parallel - capped, ordered, and one failure
does not throw away the chunks that finished.
"""

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
)
from boosty_downloader.application.run_statistics import RunStatistics
from boosty_downloader.application.use_cases import (
    download_single_post as usecase_module,
)
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkFile,
    PostDataChunkImage,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenFile,
    HtmlGenImage,
    HtmlGenUnavailable,
    UnavailableKind,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.domain.post import PostDataAllChunks
    from boosty_downloader.infrastructure.html_generator.models import HtmlGenChunk

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
FILES = DownloadContentTypeFilter.files
POST_CONTENT = DownloadContentTypeFilter.post_content


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
    def __init__(self) -> None:
        self.cached: list[list[DownloadContentTypeFilter]] = []

    def get_post_missing_parts(
        self, **kwargs: object
    ) -> list[DownloadContentTypeFilter]:
        del kwargs
        return [FILES, POST_CONTENT]

    def cache_post(
        self,
        post_uuid: str,
        updated_at: datetime,
        parts: list[DownloadContentTypeFilter],
    ) -> None:
        del post_uuid, updated_at
        self.cached.append(parts)

    def commit(self) -> None:
        pass


class _Context:
    def __init__(self) -> None:
        self.progress_reporter = _FakeReporter()
        self.post_cache = _FakeCache()
        self.filters = [FILES, POST_CONTENT]
        self.preferred_video_quality = BoostyOkVideoType.medium
        self.run_statistics = RunStatistics()


def _file(n: int) -> dict[str, object]:
    return {
        'type': 'file',
        'id': f'f{n}',
        'url': f'https://cdn/f{n}',
        'title': f'file-{n}.bin',
        'size': 1,
        'complete': True,
    }


def _image() -> dict[str, object]:
    return {'type': 'image', 'url': 'https://cdn/image/i1', 'size': 1}


def _post_dto(chunks: list[dict[str, object]]) -> PostDTO:
    return PostDTO(
        id='p1',
        title='parallel post',
        created_at=NOW,
        updated_at=NOW,
        has_access=True,
        signed_query='',
        data=chunks,
    )


def _use_case(
    tmp_path: Path, chunks: list[dict[str, object]]
) -> tuple[DownloadSinglePostUseCase, _Context]:
    context = _Context()
    use_case = DownloadSinglePostUseCase(
        destination=tmp_path / 'post',
        post_dto=_post_dto(chunks),
        download_context=cast('DownloadContext', context),
    )
    return use_case, context


def _patch_render(monkeypatch: pytest.MonkeyPatch) -> list[list[HtmlGenChunk]]:
    rendered: list[list[HtmlGenChunk]] = []

    def fake_render(chunks: list[HtmlGenChunk], **kwargs: object) -> None:
        del kwargs
        rendered.append(chunks)

    monkeypatch.setattr(usecase_module, 'render_html_to_file', fake_render)
    return rendered


def _fail(name: str) -> ApplicationFailedDownloadError:
    return ApplicationFailedDownloadError(
        post_uuid='p1', message='dead link', resource=name
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

    monkeypatch.setattr(DownloadSinglePostUseCase, '_safely_process_chunk', scripted)
    rendered = _patch_render(monkeypatch)

    started = time.monotonic()
    use_case, _ = _use_case(tmp_path, [_file(n) for n in range(6)])
    await use_case.execute()
    duration = time.monotonic() - started

    assert max_active <= 4, 'the semaphore must cap concurrency at 4'
    assert max_active >= 2, 'chunks must actually overlap'
    assert duration < 0.25, f'6x50ms must not run sequentially (took {duration:.2f}s)'
    assert rendered == [[f'file-{n}.bin' for n in range(6)]], (
        'the page must keep the original chunk order'
    )


async def test_one_failed_chunk_lets_the_others_finish_and_keeps_their_types(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A dead file must not throw away the rest of the post: the siblings run to
    the end, the page renders without the failed attachment, post_content is
    cached, files is not - and the failure still reaches the retrier.
    """
    cancelled = 0

    async def scripted(
        self: DownloadSinglePostUseCase,
        chunk: PostDataAllChunks,
        missing: object,
        post: object,
    ) -> object:
        del self, missing, post
        nonlocal cancelled
        name = cast('PostDataChunkFile', chunk).filename
        if name == 'file-0.bin':
            await asyncio.sleep(0.01)
            raise _fail(name)
        try:
            await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            cancelled += 1
            raise
        return None

    monkeypatch.setattr(DownloadSinglePostUseCase, '_safely_process_chunk', scripted)
    rendered = _patch_render(monkeypatch)
    use_case, context = _use_case(tmp_path, [_file(n) for n in range(4)])

    with pytest.raises(ApplicationFailedDownloadError) as info:
        await use_case.execute()

    assert info.value.resource == 'file-0.bin'
    assert cancelled == 0, 'the siblings must finish, not get cancelled'
    assert rendered == [[]], 'the page renders; the failed attachment is not on it'
    assert context.post_cache.cached == [[POST_CONTENT]]
    assert context.run_statistics.posts_downloaded == 0


async def test_a_failed_page_element_becomes_a_placeholder_and_keeps_the_page_uncached(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The page is written with a note at the image's place, so the post stays
    readable. post_content is not cached: a cached page with a hole could never
    be rewritten, an uncached one is rewritten by the retry or the next run.
    """
    image_ok = False

    async def scripted(
        self: DownloadSinglePostUseCase,
        chunk: PostDataAllChunks,
        missing: object,
        post: object,
    ) -> object:
        del self, missing, post
        if not isinstance(chunk, PostDataChunkImage):
            return None
        if image_ok:
            return HtmlGenImage(url='images/i1.png')
        image_failure = _fail('i1')
        raise image_failure

    monkeypatch.setattr(DownloadSinglePostUseCase, '_safely_process_chunk', scripted)
    rendered = _patch_render(monkeypatch)
    use_case, context = _use_case(tmp_path, [_image(), _file(0), _file(1)])

    with pytest.raises(ApplicationFailedDownloadError):
        await use_case.execute()

    assert rendered == [
        [HtmlGenUnavailable(kind=UnavailableKind.IMAGE, reason='dead link')]
    ]
    assert context.post_cache.cached == [[FILES]], 'a page with a hole is not cached'

    # The retry brings the image: the page is rewritten without the note.
    image_ok = True
    await use_case.execute()

    assert rendered[-1] == [HtmlGenImage(url='images/i1.png')]
    assert context.post_cache.cached[-1] == [FILES, POST_CONTENT]


async def test_a_retry_keeps_the_page_elements_of_the_earlier_attempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A retry fetches the failed type only; the page must still carry the pieces
    that landed before, or a rewrite after a retry would drop the videos and files
    of the first attempt.
    """
    file_card = HtmlGenFile(url='files/file-0.bin', filename='file-0.bin')
    image_ok = False

    async def scripted(
        self: DownloadSinglePostUseCase,
        chunk: PostDataAllChunks,
        missing: object,
        post: object,
    ) -> object:
        del self, missing, post
        if isinstance(chunk, PostDataChunkFile):
            # Cached after the first attempt: the retry does not touch it.
            return None if image_ok else file_card
        if image_ok:
            return HtmlGenImage(url='images/i1.png')
        image_failure = _fail('i1')
        raise image_failure

    monkeypatch.setattr(DownloadSinglePostUseCase, '_safely_process_chunk', scripted)
    rendered = _patch_render(monkeypatch)
    use_case, _ = _use_case(tmp_path, [_image(), _file(0)])

    with pytest.raises(ApplicationFailedDownloadError):
        await use_case.execute()
    image_ok = True
    # Fresh signed links rebuild the use case; the page travels with them.
    fresh_use_case, _ = _use_case(tmp_path, [_image(), _file(0)])
    fresh_use_case.take_page_from(use_case)
    await fresh_use_case.execute()

    assert rendered[-1] == [HtmlGenImage(url='images/i1.png'), file_card]


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

    use_case, _ = _use_case(tmp_path, [_file(n) for n in range(3)])
    task = asyncio.create_task(use_case.execute())
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(ApplicationCancelledError):
        await task
