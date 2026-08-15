"""The --post-url flow asks the API for one post instead of walking pages."""

from __future__ import annotations

import uuid as uuid_module
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

from boosty_downloader.src.application.di.download_context import DownloadContext
from boosty_downloader.src.application.filtering import BoostyOkVideoType
from boosty_downloader.src.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.src.application.use_cases.download_specific_post import (
    DownloadPostByUrlUseCase,
)
from boosty_downloader.src.infrastructure.boosty_api.core.client import (
    BoostyAPINoPostError,
    BoostyAPIValidationError,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO

if TYPE_CHECKING:
    import pytest
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

POST_UUID = 'a2dd6942-7297-4340-a19f-d637fa8ef4de'
POST_URL = f'https://boosty.to/author/posts/{POST_UUID}'


class _FakeReporter:
    """Collects messages instead of rendering rich output."""

    def __init__(self) -> None:
        self.errors: list[str] = []
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
        del message

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


def _use_case(api: _FakeApi, reporter: _FakeReporter) -> DownloadPostByUrlUseCase:
    context = DownloadContext(
        author_name='author',
        downloader_session=cast('RetryClient', None),
        external_videos_downloader=cast('ExternalVideosDownloader', None),
        post_cache=cast('SQLitePostCache', None),
        filters=[],
        preferred_video_quality=BoostyOkVideoType.medium,
        progress_reporter=cast('ProgressReporter', reporter),
        failed_logger=cast('FailedDownloadsLogger', None),
    )
    return DownloadPostByUrlUseCase(
        post_url=POST_URL,
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


async def test_post_downloads_via_one_direct_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Walking 100-post pages made --post-url slow and stale-link-prone."""
    reporter = _FakeReporter()
    api = _FakeApi(post=_post())
    calls = _script_download(monkeypatch)

    await _use_case(api, reporter).execute()

    assert api.requests == [('author', POST_UUID)]
    assert calls == [POST_UUID]
    assert reporter.errors == []


async def test_missing_post_reports_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reporter = _FakeReporter()
    api = _FakeApi(error=BoostyAPINoPostError('author', POST_UUID))
    calls = _script_download(monkeypatch)

    await _use_case(api, reporter).execute()

    assert calls == []
    assert any('Failed to find' in message for message in reporter.errors)


async def test_unparsable_post_asks_to_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A misleading 'not found' would hide that the client needs an update."""
    reporter = _FakeReporter()
    api = _FakeApi(error=BoostyAPIValidationError(errors=[]))
    calls = _script_download(monkeypatch)

    await _use_case(api, reporter).execute()

    assert calls == []
    assert any('Please report this' in message for message in reporter.errors)


async def test_no_access_post_is_not_downloaded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Downloading a paywalled post would save an empty preview as content."""
    reporter = _FakeReporter()
    api = _FakeApi(post=_post(has_access=False))
    calls = _script_download(monkeypatch)

    await _use_case(api, reporter).execute()

    assert calls == []
    assert any('no access' in message for message in reporter.errors)
