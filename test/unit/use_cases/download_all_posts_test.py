"""Containment tests: one broken post must never kill or hollow out the run."""

from __future__ import annotations

import errno
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from boosty_downloader.src.application.di.download_context import DownloadContext
from boosty_downloader.src.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationTooManyFailuresError,
)
from boosty_downloader.src.application.filtering import BoostyOkVideoType
from boosty_downloader.src.application.use_cases.download_all_posts import (
    DownloadAllPostUseCase,
)
from boosty_downloader.src.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.extra import Extra
from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.src.infrastructure.boosty_api.models.post.posts_request import (
    PostsResponse,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from aiohttp_retry import RetryClient

    from boosty_downloader.src.cli.console_progress_reporter import ProgressReporter
    from boosty_downloader.src.infrastructure.boosty_api.core.client import (
        BoostyAPIClient,
    )
    from boosty_downloader.src.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )
    from boosty_downloader.src.infrastructure.loggers.failed_downloads_logger import (
        FailedDownloadsLogger,
    )
    from boosty_downloader.src.infrastructure.post_caching.post_cache import (
        SQLitePostCache,
    )


class _FakeReporter:
    """Collects messages instead of rendering rich output."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def create_task(self, *args: object, **kwargs: object) -> uuid.UUID:
        del args, kwargs
        return uuid.uuid4()

    def update_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def complete_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def success(self, message: str) -> None:
        del message

    def notice(self, message: str) -> None:
        del message

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


class _FakeFailedLogger:
    """Collects failed-post log entries instead of writing a file."""

    def __init__(self) -> None:
        self.entries: list[tuple[str, str]] = []

    async def add_error(self, error_id: str, message: str) -> None:
        self.entries.append((error_id, message))


class _FakeApi:
    """One page of posts, then stop."""

    def __init__(self, page: PostsResponse) -> None:
        self._page = page

    async def iterate_over_posts(
        self, *args: object, **kwargs: object
    ) -> AsyncGenerator[PostsResponse, None]:
        del args, kwargs
        yield self._page


def _post(post_id: str) -> PostDTO:
    return PostDTO(
        id=post_id,
        title=f'post {post_id}',
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        has_access=True,
        signed_query='',
        data=[],
    )


def _use_case(
    post_ids: list[str],
    reporter: _FakeReporter,
    failed_logger: _FakeFailedLogger,
    *,
    skip_all_failures: bool = False,
) -> DownloadAllPostUseCase:
    page = PostsResponse(
        posts=[_post(post_id) for post_id in post_ids],
        extra=Extra(offset='', is_last=True),
    )
    context = DownloadContext(
        author_name='author',
        downloader_session=cast('RetryClient', None),
        external_videos_downloader=cast('ExternalVideosDownloader', None),
        post_cache=cast('SQLitePostCache', None),
        filters=[],
        preferred_video_quality=BoostyOkVideoType.medium,
        progress_reporter=cast('ProgressReporter', reporter),
        failed_logger=cast('FailedDownloadsLogger', failed_logger),
    )
    return DownloadAllPostUseCase(
        author_name='author',
        boosty_api=cast('BoostyAPIClient', _FakeApi(page)),
        destination=Path('unused'),
        download_context=context,
        skip_all_failures=skip_all_failures,
    )


def _script_outcomes(
    monkeypatch: pytest.MonkeyPatch, outcomes: dict[str, Exception]
) -> list[str]:
    """Replace the single-post download with a script: raise by post id or succeed."""
    calls: list[str] = []

    async def scripted_execute(self: DownloadSinglePostUseCase) -> None:
        calls.append(self.post_dto.id)
        error = outcomes.get(self.post_dto.id)
        if error is not None:
            raise error

    monkeypatch.setattr(DownloadSinglePostUseCase, 'execute', scripted_execute)
    return calls


@pytest.mark.asyncio
async def test_unexpected_error_skips_the_post_and_the_run_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for #88: an uncaught OSError used to kill the whole run."""
    reporter = _FakeReporter()
    failed_logger = _FakeFailedLogger()
    calls = _script_outcomes(monkeypatch, {'p1': OSError('File name too long')})

    await _use_case(['p1', 'p2'], reporter, failed_logger).execute()

    assert calls == ['p1', 'p2'], 'the run must reach the post after the broken one'
    assert failed_logger.entries, 'the skip must land in failed_downloads.log'
    assert failed_logger.entries[0][0] == 'p1'
    summary = reporter.warnings[-1]
    assert 'failed to download' in summary
    assert 'post p1' in summary


@pytest.mark.asyncio
async def test_path_too_long_error_carries_the_folder_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare 'File name too long' leaves the user without a way out (#93)."""
    reporter = _FakeReporter()
    failed_logger = _FakeFailedLogger()
    error = OSError(errno.ENAMETOOLONG, 'File name too long')
    _script_outcomes(monkeypatch, {'p1': error})

    await _use_case(['p1'], reporter, failed_logger).execute()

    hint = 'move the destination folder closer to the drive root'
    assert any(hint in message for message in reporter.errors)
    assert any(hint in message for _, message in failed_logger.entries)


@pytest.mark.asyncio
async def test_cancellation_reraises_and_stops_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+C guard: the containment branch must never swallow cancellation."""
    reporter = _FakeReporter()
    failed_logger = _FakeFailedLogger()
    calls = _script_outcomes(
        monkeypatch, {'p1': ApplicationCancelledError(post_uuid='p1')}
    )

    with pytest.raises(ApplicationCancelledError):
        await _use_case(['p1', 'p2'], reporter, failed_logger).execute()

    assert calls == ['p1'], 'nothing after the cancelled post may be downloaded'


@pytest.mark.asyncio
async def test_failure_streak_stops_the_run_with_a_systemic_diagnosis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A systemic cause must stop the run early, not grind through every post."""
    reporter = _FakeReporter()
    failed_logger = _FakeFailedLogger()
    post_ids = [f'p{n}' for n in range(1, 7)]
    calls = _script_outcomes(
        monkeypatch, {post_id: OSError('disk full') for post_id in post_ids}
    )

    with pytest.raises(ApplicationTooManyFailuresError):
        await _use_case(post_ids, reporter, failed_logger).execute()

    assert len(calls) == 5, 'the run must stop right at the threshold'
    diagnosis = reporter.errors[-1]
    assert 'systemic' in diagnosis
    assert 'cached' in diagnosis, 'the stop message must explain how to resume'


@pytest.mark.asyncio
async def test_success_resets_the_streak(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scattered failures are per-post problems - the run must reach the end."""
    reporter = _FakeReporter()
    failed_logger = _FakeFailedLogger()
    post_ids = [f'p{n}' for n in range(1, 10)]
    failing = {post_id: OSError('flaky') for post_id in post_ids if post_id != 'p5'}
    calls = _script_outcomes(monkeypatch, cast('dict[str, Exception]', failing))

    await _use_case(post_ids, reporter, failed_logger).execute()

    assert len(calls) == 9, 'four failures, a success, four more - never a stop'


@pytest.mark.asyncio
async def test_skip_all_failures_never_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The --skip-all-failures escape hatch: the run always reaches the end."""
    reporter = _FakeReporter()
    failed_logger = _FakeFailedLogger()
    post_ids = [f'p{n}' for n in range(1, 8)]
    calls = _script_outcomes(
        monkeypatch, {post_id: OSError('disk full') for post_id in post_ids}
    )

    await _use_case(post_ids, reporter, failed_logger, skip_all_failures=True).execute()

    assert len(calls) == 7, 'every post must be attempted despite the streak'
    summary = reporter.warnings[-1]
    assert 'failed to download (7)' in summary
