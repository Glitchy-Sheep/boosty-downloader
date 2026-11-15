"""Optional author refreshes preserve saved metadata when an update cannot finish."""

from __future__ import annotations

from asyncio import CancelledError
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, cast

import pytest
from support.memory_post_store import MemoryPostStore
from support.synthetic_blog import (
    BLOG_TITLE,
    DESCRIPTION_TEXT,
    OWNER_NAME,
    POST_COUNT,
    synthetic_blog,
)

from boosty_downloader.application import author_sync
from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.domain.stored_post import AuthorInfo
from boosty_downloader.infrastructure.author_images import AuthorImageKind
from boosty_downloader.infrastructure.boosty_api.core.client import (
    BoostyAPITransportError,
    BoostyAPIUnknownError,
)
from boosty_downloader.infrastructure.boosty_api.models.blog import BlogInfoDTO
from boosty_downloader.infrastructure.file_downloader import (
    DownloadCancelledError,
    DownloadTimeoutError,
)
from boosty_downloader.infrastructure.library.errors import InvalidAuthorRecordError

if TYPE_CHECKING:
    from pathlib import Path

    from aiohttp_retry import RetryClient

    from boosty_downloader.application.ports import FailureLog, ProgressReporter
    from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )

AUTHOR = 'fixture-author'
OLD_SYNC = datetime(2026, 1, 1, tzinfo=timezone.utc)
AVATAR_URL = 'https://images.example/blog/avatar.png'
COVER_URL = 'https://images.example/blog/cover.png'


class _Api:
    def __init__(self) -> None:
        self.blog = BlogInfoDTO.model_validate(synthetic_blog())
        self.calls: list[str] = []
        self.error: BaseException | None = None

    async def get_blog_info(self, author: str) -> BlogInfoDTO:
        self.calls.append(author)
        if self.error is not None:
            raise self.error
        return self.blog


class _Reporter:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warn(self, message: str) -> None:
        self.warnings.append(message)


class _Store(MemoryPostStore):
    def __init__(self) -> None:
        super().__init__()
        self.load_error: Exception | None = None
        self.save_error: Exception | None = None

    def load_author(self, author: str) -> AuthorInfo | None:
        if self.load_error is not None:
            raise self.load_error
        return super().load_author(author)

    def save_author(self, author: AuthorInfo) -> None:
        if self.save_error is not None:
            raise self.save_error
        super().save_author(author)


@dataclass(frozen=True)
class _ImageRequest:
    kind: AuthorImageKind
    url: str
    author: str
    root: Path


class _Images:
    def __init__(self) -> None:
        self.calls: list[_ImageRequest] = []
        self.failures: dict[AuthorImageKind, BaseException] = {}

    async def download(
        self,
        *,
        session: RetryClient,
        library_root: Path,
        author: str,
        kind: AuthorImageKind,
        url: str,
    ) -> str:
        del session
        self.calls.append(_ImageRequest(kind, url, author, library_root))
        if kind in self.failures:
            raise self.failures[kind]
        return f'.boosty-downloader/{kind.value}.png'


@dataclass
class _Run:
    api: _Api
    store: _Store
    reporter: _Reporter
    images: _Images
    context: DownloadContext

    async def refresh(self) -> None:
        await author_sync.refresh_author(
            cast('BoostyAPIClient', self.api), self.context
        )


@pytest.fixture
def run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Run:
    api, store, reporter, images = _Api(), _Store(), _Reporter(), _Images()
    context = DownloadContext(
        author_name=AUTHOR,
        downloader_session=cast('RetryClient', None),
        external_videos_downloader=cast('ExternalVideosDownloader', None),
        post_store=store,
        library_root=tmp_path,
        filters=[],
        preferred_video_quality=BoostyOkVideoType.medium,
        progress_reporter=cast('ProgressReporter', reporter),
        failed_logger=cast('FailureLog', None),
    )
    monkeypatch.setattr(author_sync, 'download_author_image', images.download)
    return _Run(api, store, reporter, images, context)


def _save_previous(run: _Run) -> AuthorInfo:
    previous = AuthorInfo(
        AUTHOR,
        OLD_SYNC,
        title='Previous title',
        owner_name='Previous owner',
        description='Previous description',
        avatar_path='.boosty-downloader/avatar.jpg',
        cover_path='.boosty-downloader/cover.webp',
        remote_post_count=2,
    )
    run.store.save_author(previous)
    return previous


async def test_refresh_saves_complete_metadata_without_counting_author_images(
    run: _Run,
) -> None:
    before_stats = deepcopy(run.context.run_statistics)
    before_time = datetime.now(timezone.utc)

    await run.refresh()

    author = run.store.load_author(AUTHOR)
    assert author is not None
    assert before_time <= author.synced_at <= datetime.now(timezone.utc)
    assert author == AuthorInfo(
        AUTHOR,
        author.synced_at,
        title=BLOG_TITLE,
        owner_name=OWNER_NAME,
        description=DESCRIPTION_TEXT,
        avatar_path='.boosty-downloader/avatar.png',
        cover_path='.boosty-downloader/cover.png',
        remote_post_count=POST_COUNT,
    )
    assert run.api.calls == [AUTHOR]
    assert run.images.calls == [
        _ImageRequest(
            AuthorImageKind.avatar, AVATAR_URL, AUTHOR, run.context.library_root
        ),
        _ImageRequest(
            AuthorImageKind.cover, COVER_URL, AUTHOR, run.context.library_root
        ),
    ]
    assert run.context.run_statistics == before_stats
    assert run.reporter.warnings == []


async def test_each_refresh_fetches_current_metadata_and_both_images(run: _Run) -> None:
    await run.refresh()
    first = run.store.load_author(AUTHOR)
    assert first is not None
    run.api.blog.title = 'Changed blog title'

    await run.refresh()

    second = run.store.load_author(AUTHOR)
    assert second is not None
    assert second.title == 'Changed blog title'
    assert second.synced_at >= first.synced_at
    assert run.api.calls == [AUTHOR, AUTHOR]
    assert [request.kind for request in run.images.calls] == list(AuthorImageKind) * 2


@pytest.mark.parametrize(
    'blog',
    [
        {},
        {'owner': None, 'coverUrl': None},
        {'owner': {'avatarUrl': ''}, 'coverUrl': ''},
    ],
    ids=['absent', 'null', 'empty'],
)
async def test_missing_image_urls_preserve_previous_paths(
    run: _Run, blog: dict[str, object]
) -> None:
    previous = _save_previous(run)
    run.api.blog = BlogInfoDTO.model_validate({'title': 'Current title', **blog})

    await run.refresh()

    saved = run.store.load_author(AUTHOR)
    assert saved is not None
    assert saved.title == 'Current title'
    assert saved.avatar_path == previous.avatar_path
    assert saved.cover_path == previous.cover_path
    assert run.images.calls == []
    assert run.reporter.warnings == []


async def test_first_refresh_without_image_urls_does_not_invent_paths(
    run: _Run,
) -> None:
    run.api.blog = BlogInfoDTO()

    await run.refresh()

    saved = run.store.load_author(AUTHOR)
    assert saved is not None
    assert saved.avatar_path is None
    assert saved.cover_path is None
    assert run.images.calls == []


@pytest.mark.parametrize('kind', list(AuthorImageKind))
@pytest.mark.parametrize(
    'error',
    [DownloadTimeoutError(AVATAR_URL), OSError('disk full'), ValueError('unsafe path')],
    ids=['transfer', 'filesystem', 'invalid-path'],
)
async def test_one_failed_image_preserves_its_path_and_allows_the_other_update(
    run: _Run, kind: AuthorImageKind, error: Exception
) -> None:
    previous = _save_previous(run)
    run.images.failures[kind] = error

    await run.refresh()

    saved = run.store.load_author(AUTHOR)
    assert saved is not None
    assert saved.title == BLOG_TITLE
    assert saved.synced_at > previous.synced_at
    assert [request.kind for request in run.images.calls] == list(AuthorImageKind)
    match kind:
        case AuthorImageKind.avatar:
            assert saved.avatar_path == previous.avatar_path
            assert saved.cover_path == '.boosty-downloader/cover.png'
        case AuthorImageKind.cover:
            assert saved.avatar_path == '.boosty-downloader/avatar.png'
            assert saved.cover_path == previous.cover_path
    assert len(run.reporter.warnings) == 1
    assert kind.value in run.reporter.warnings[0]
    assert str(error) in run.reporter.warnings[0]


@pytest.mark.parametrize(
    'error',
    [
        BoostyAPIUnknownError(503, 'temporarily unavailable'),
        BoostyAPITransportError('Cannot read blog metadata from Boosty'),
    ],
    ids=['api-status', 'transport'],
)
async def test_blog_failure_preserves_snapshot_without_downloading_images(
    run: _Run,
    error: Exception,
) -> None:
    previous = _save_previous(run)
    run.api.error = error

    await run.refresh()

    assert run.store.load_author(AUTHOR) == previous
    assert run.api.calls == [AUTHOR]
    assert run.images.calls == []
    assert len(run.reporter.warnings) == 1
    assert str(error) in run.reporter.warnings[0]


async def test_invalid_saved_author_prevents_asset_writes(run: _Run) -> None:
    previous = _save_previous(run)
    run.store.load_error = InvalidAuthorRecordError(
        'Author record belongs to another author'
    )

    await run.refresh()

    run.store.load_error = None
    assert run.store.load_author(AUTHOR) == previous
    assert run.images.calls == []
    assert len(run.reporter.warnings) == 1
    assert 'belongs to another author' in run.reporter.warnings[0]


async def test_save_failure_warns_and_preserves_the_prior_snapshot(run: _Run) -> None:
    previous = _save_previous(run)
    run.store.save_error = OSError('metadata disk full')

    await run.refresh()

    assert run.store.load_author(AUTHOR) == previous
    assert len(run.reporter.warnings) == 1
    assert 'metadata disk full' in run.reporter.warnings[0]


@pytest.mark.parametrize('content', ['[]', '{}', '[null, "unstyled", []]'])
async def test_malformed_description_warns_without_replacing_metadata_or_images(
    run: _Run, content: str
) -> None:
    previous = _save_previous(run)
    payload = synthetic_blog()
    payload['description'] = [{'type': 'text', 'content': content, 'modificator': ''}]
    run.api.blog = BlogInfoDTO.model_validate(payload)

    await run.refresh()

    assert run.store.load_author(AUTHOR) == previous
    assert run.images.calls == []
    assert len(run.reporter.warnings) == 1
    assert 'Blog description' in run.reporter.warnings[0]


async def test_cancelled_blog_request_propagates_without_warnings(run: _Run) -> None:
    previous = _save_previous(run)
    run.api.error = CancelledError()

    with pytest.raises(CancelledError):
        await run.refresh()

    assert run.store.load_author(AUTHOR) == previous
    assert run.images.calls == []
    assert run.reporter.warnings == []


@pytest.mark.parametrize(
    'error',
    [CancelledError(), DownloadCancelledError(AVATAR_URL)],
    ids=['task-cancelled', 'transfer-cancelled'],
)
@pytest.mark.parametrize('kind', list(AuthorImageKind))
async def test_cancelled_image_aborts_refresh_without_saving_partial_metadata(
    run: _Run, error: BaseException, kind: AuthorImageKind
) -> None:
    previous = _save_previous(run)
    run.images.failures[kind] = error

    with pytest.raises(CancelledError):
        await run.refresh()

    assert run.store.load_author(AUTHOR) == previous
    expected = [AuthorImageKind.avatar]
    if kind is AuthorImageKind.cover:
        expected.append(AuthorImageKind.cover)
    assert [request.kind for request in run.images.calls] == expected
    assert run.reporter.warnings == []
