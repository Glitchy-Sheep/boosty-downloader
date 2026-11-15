"""Production download wiring for subprocess interruption acceptance tests."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock, patch
from uuid import uuid4

from aiohttp import ClientSession
from aiohttp_retry import ExponentialRetry, RetryClient
from yarl import URL

from boosty_downloader.application.download_context import DownloadContext
from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.ports import ProgressReporter
from boosty_downloader.application.post_download_state import PostDownloadState
from boosty_downloader.application.post_retry import PostOutcome
from boosty_downloader.application.use_cases.download_post_by_id import (
    DownloadPostByIdUseCase,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.loggers.failed_downloads_logger import (
    FailedDownloadsLogger,
)
from support.synthetic_post import POST_ID

if TYPE_CHECKING:
    from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
        ExternalVideosDownloader,
    )
    from boosty_downloader.infrastructure.media_publication import PublishedFile

AUTHOR = 'interruption-fixture'


async def _download(root: Path, api_base: URL) -> int:
    reporter = Mock(spec=ProgressReporter)
    reporter.create_task.return_value = uuid4()
    async with (
        ClientSession() as session,
        RetryClient(session, retry_options=ExponentialRetry(attempts=1)) as client,
    ):
        context = DownloadContext(
            author_name=AUTHOR,
            downloader_session=client,
            external_videos_downloader=cast('ExternalVideosDownloader', None),
            post_store=JsonPostStore(root),
            library_root=root,
            filters=[DownloadContentTypeFilter.boosty_videos],
            preferred_video_quality=BoostyOkVideoType.medium,
            progress_reporter=reporter,
            failed_logger=FailedDownloadsLogger(root / AUTHOR / 'failed_downloads.log'),
        )
        outcome = await DownloadPostByIdUseCase(
            post_id=POST_ID,
            boosty_api=BoostyAPIClient(client, base_url=api_base / 'v1/'),
            destination=root / AUTHOR,
            download_context=context,
        ).execute()
    sys.stdout.write(f'{outcome.name} {context.run_statistics.downloaded_bytes}\n')
    if outcome is not PostOutcome.downloaded:
        sys.stderr.write(f'{reporter.method_calls!r}\n')
        return 1
    return 0


def _run(root: Path, api_base: URL, published_signal: Path | None) -> int:
    if published_signal is None:
        return asyncio.run(_download(root, api_base))

    def pause_before_complete(
        _state: PostDownloadState, _media_id: str, result: PublishedFile
    ) -> bool:
        assert result.path.is_file()
        published_signal.write_bytes(b'published before completed-state save')
        Event().wait()
        message = 'The parent must stop this child at the publication boundary'
        raise AssertionError(message)

    with patch.object(PostDownloadState, 'complete', pause_before_complete):
        return asyncio.run(_download(root, api_base))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('library_root', type=Path)
    parser.add_argument('api_base', type=URL)
    parser.add_argument('--published-signal', type=Path)
    args = parser.parse_args()
    return _run(args.library_root, args.api_base, args.published_signal)


if __name__ == '__main__':
    raise SystemExit(main())
