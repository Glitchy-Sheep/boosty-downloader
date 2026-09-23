"""The --post-url flow asks the API for one post and downloads it like the full run does."""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from boosty_downloader.application import post_retry as post_retry_module
from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.exceptions.application_errors import (
    ApplicationCancelledError,
    ApplicationFailedDownloadError,
)
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.post_retry import PostOutcome
from boosty_downloader.application.use_cases.download_post_by_id import (
    DownloadPostByIdUseCase,
)
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPINoPostError,
    BoostyAPIValidationError,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.file_downloader import (
    DownloadUnexpectedStatusError,
)

if TYPE_CHECKING:
    from aiohttp_retry import RetryClient

    from boosty_downloader.application.ports import FailureLog, PostCache
    from boosty_downloader.infrastructure.boosty_api.core.client import (
        BoostyAPIClient,
    )
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )

POST_UUID = '20000000-0000-4000-8000-000000000042'


class _FakeReporter:
    """Collects messages instead of rendering rich output."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def create_task(self, *args: object, **kwargs: object) -> uuid_module.UUID:
        del args, kwargs
        return uuid_module.uuid4()

    def update_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def complete_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def success(self, message: str) -> None:
        del message

    def notice(self, message: str) -> None:
        del message

    def info(self, message: str) -> None:
        self.infos.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def error(self, message: str) -> None:
        self.errors.append(message)


class _FakeApi:
    """Answers get_single_post with a prepared post or a prepared error."""

    def __init__(
        self, post: PostDTO | None = None, error: Exception | None = None
    ) -> None:
        self._post = post
        self._error = error
        self.requests: list[tuple[str, str]] = []

    async def get_single_post(self, author_name: str, post_id: str) -> PostDTO:
        self.requests.append((author_name, post_id))
        if self._error is not None:
            raise self._error
        assert self._post is not None
        return self._post


def _post(*, has_access: bool = True) -> PostDTO:
    return PostDTO(
        id=POST_UUID,
        title='post',
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        has_access=has_access,
        signed_query='',
        data=[],
    )


def _use_case(api: _FakeApi, reporter: _FakeReporter) -> DownloadPostByIdUseCase:
    context = DownloadContext(
        author_name='author',
        downloader_session=cast('RetryClient', None),
        external_videos_downloader=cast('ExternalVideosDownloader', None),
        post_cache=cast('PostCache', None),
        filters=[],
        preferred_video_quality=BoostyOkVideoType.medium,
        progress_reporter=reporter,
        failed_logger=cast('FailureLog', None),
    )
    return DownloadPostByIdUseCase(
        post_id=POST_UUID,
        boosty_api=cast('BoostyAPIClient', api),
        destination=Path('unused'),
        download_context=context,
    )


def _script_download(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def scripted_execute(self: DownloadSinglePostUseCase) -> None:
        calls.append(self.post_dto.id)

    monkeypatch.setattr(DownloadSinglePostUseCase, 'execute', scripted_execute)
    return calls


def _script_download_error(
    monkeypatch: pytest.MonkeyPatch, error: BaseException
) -> None:
    async def failing_execute(self: DownloadSinglePostUseCase) -> None:
        del self
        raise error

    monkeypatch.setattr(DownloadSinglePostUseCase, 'execute', failing_execute)


def _disable_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(delay: float) -> None:
        del delay

    monkeypatch.setattr(post_retry_module.asyncio, 'sleep', _no_sleep)


def _expired_error() -> ApplicationFailedDownloadError:
    error = ApplicationFailedDownloadError(
        post_uuid=POST_UUID, message='Unexpected status code: 400', resource='r'
    )
    error.__cause__ = DownloadUnexpectedStatusError(
        status=400, response_message='Bad Request', resource_url='https://cdn/x'
    )
    return error


async def test_post_downloads_via_one_direct_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walking 100-post pages made --post-url slow and stale-link-prone."""
    reporter = _FakeReporter()
    api = _FakeApi(post=_post())
    calls = _script_download(monkeypatch)

    outcome = await _use_case(api, reporter).execute()

    assert api.requests == [('author', POST_UUID)]
    assert calls == [POST_UUID]
    assert reporter.errors == []
    assert outcome is PostOutcome.downloaded


async def test_missing_post_reports_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reporter = _FakeReporter()
    api = _FakeApi(error=BoostyAPINoPostError('author', POST_UUID))
    calls = _script_download(monkeypatch)

    outcome = await _use_case(api, reporter).execute()

    assert calls == []
    assert any('Failed to find' in message for message in reporter.errors)
    assert outcome is PostOutcome.failed, 'a script must see the failure in $?'


async def test_unparsable_post_asks_to_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A misleading 'not found' would hide that the client needs an update."""
    reporter = _FakeReporter()
    api = _FakeApi(error=BoostyAPIValidationError(errors=[]))
    calls = _script_download(monkeypatch)

    outcome = await _use_case(api, reporter).execute()

    assert calls == []
    assert any('Please report this' in message for message in reporter.errors)
    assert outcome is PostOutcome.failed


async def test_no_access_post_is_not_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downloading a paywalled post would save an empty preview as content."""
    reporter = _FakeReporter()
    api = _FakeApi(post=_post(has_access=False))
    calls = _script_download(monkeypatch)
    use_case = _use_case(api, reporter)

    outcome = await use_case.execute()

    assert calls == []
    assert any('no access' in message for message in reporter.errors)
    assert outcome is PostOutcome.failed
    assert use_case.context.run_statistics.posts_locked == 1


async def test_failed_download_is_retried_then_a_failed_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead link used to end --post-url with exit 0 and no retry at all."""
    reporter = _FakeReporter()
    api = _FakeApi(post=_post())
    _script_download_error(
        monkeypatch,
        ApplicationFailedDownloadError(
            post_uuid=POST_UUID, message='dead link', resource='r'
        ),
    )
    _disable_retry_sleep(monkeypatch)
    use_case = _use_case(api, reporter)

    outcome = await use_case.execute()

    assert outcome is PostOutcome.failed
    assert any('Skip post after 5 failed attempts' in m for m in reporter.errors)
    assert use_case.context.run_statistics.posts_failed == 1


async def test_a_gone_video_ends_the_post_after_one_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Issue #76: five attempts on a deleted video, minutes of noise for nothing."""
    reporter = _FakeReporter()
    api = _FakeApi(post=_post())
    _script_download_error(
        monkeypatch,
        ApplicationFailedDownloadError(
            post_uuid=POST_UUID,
            message='External video unavailable: This video is unavailable',
            resource='https://www.youtube.com/watch?v=gone',
            retryable=False,
        ),
    )
    _disable_retry_sleep(monkeypatch)
    use_case = _use_case(api, reporter)

    outcome = await use_case.execute()

    assert outcome is PostOutcome.unavailable
    assert not any('Attempt 1 failed' in m for m in reporter.warnings)
    assert any(
        'Skip post, retrying will not help' in m and 'This video is unavailable' in m
        for m in reporter.errors
    )
    assert use_case.context.run_statistics.posts_failed == 1


async def test_expired_link_is_refreshed_like_in_the_full_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bug Б6: a huge video whose signed link died mid-way was lost for good."""
    reporter = _FakeReporter()
    api = _FakeApi(post=_post())
    attempts = 0

    async def failing_then_ok(self: DownloadSinglePostUseCase) -> None:
        del self
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _expired_error()

    monkeypatch.setattr(DownloadSinglePostUseCase, 'execute', failing_then_ok)
    _disable_retry_sleep(monkeypatch)

    outcome = await _use_case(api, reporter).execute()

    assert outcome is PostOutcome.downloaded
    assert api.requests == [('author', POST_UUID)] * 2, 'the post is fetched again'
    assert any('refreshing the post' in w for w in reporter.warnings)
    assert reporter.errors == []


async def test_cancellation_propagates_for_the_130_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Swallowing Ctrl+C here reported an interrupted run as a success."""
    reporter = _FakeReporter()
    api = _FakeApi(post=_post())
    _script_download_error(monkeypatch, ApplicationCancelledError(post_uuid=POST_UUID))

    with pytest.raises(ApplicationCancelledError):
        await _use_case(api, reporter).execute()
