"""What a saved attachment becomes on post.html.

The media downloader is faked; the chunk path of the use case is real.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import uuid4

from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post_data_chunks import PostDataChunkFile
from boosty_downloader.infrastructure.html_generator.models import HtmlGenFile

if TYPE_CHECKING:
    from uuid import UUID

    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
    from boosty_downloader.infrastructure.post_media_downloader import (
        PostMediaDownloader,
        ProgressCallback,
    )

FILES = DownloadContentTypeFilter.files
POST_CONTENT = DownloadContentTypeFilter.post_content
ATTACHMENT = PostDataChunkFile(
    url='https://cdn.example/f', filename='report.pdf', size=4321
)


class _QuietReporter:
    def create_task(self, *args: object, **kwargs: object) -> UUID:
        del args, kwargs
        return uuid4()

    def update_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs

    def complete_task(self, *args: object, **kwargs: object) -> None:
        del args, kwargs


class _Context:
    def __init__(self) -> None:
        self.progress_reporter = _QuietReporter()


class _SavingMedia:
    """Pretends the attachment landed under files/ without touching the network."""

    async def download_file(
        self, file: PostDataChunkFile, on_progress: ProgressCallback
    ) -> Path:
        del on_progress
        return Path('files') / file.filename


def _use_case() -> DownloadSinglePostUseCase:
    use_case = DownloadSinglePostUseCase(
        destination=Path('unused'),
        post_dto=cast('PostDTO', None),
        download_context=cast('DownloadContext', _Context()),
    )
    # cached_property: the instance value wins over the lazily built downloader.
    use_case._media = cast('PostMediaDownloader', _SavingMedia())
    return use_case


async def test_a_saved_attachment_becomes_a_link_on_the_page() -> None:
    """Files used to land in files/ while post.html never mentioned them."""
    element = await _use_case()._process_chunk(ATTACHMENT, [FILES, POST_CONTENT])

    assert element == HtmlGenFile(
        url=str(Path('files') / 'report.pdf'), filename='report.pdf', size=4321
    )


async def test_an_attachment_downloaded_outside_a_page_run_gets_no_element() -> None:
    """The page is not rendered this run: the file still lands, nothing to show."""
    element = await _use_case()._process_chunk(ATTACHMENT, [FILES])

    assert element is None
