"""Characterization of the content-filter gate (pre-refactoring safety net).

`_should_execute` decides whether a post is worth touching given the parts
still missing. Pins the chunk-to-filter mapping before the use-case split.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from boosty_downloader.application.filtering import DownloadContentTypeFilter
from boosty_downloader.application.use_cases.download_single_post import (
    DownloadSinglePostUseCase,
)
from boosty_downloader.domain.post import Post
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
    PostDataChunkText,
    PostDataChunkTextualList,
)

if TYPE_CHECKING:
    from boosty_downloader.application.di.download_context import DownloadContext
    from boosty_downloader.domain.post import (
        PostDataAllChunks,
        PostDataAllChunksList,
    )
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
ALL_FILTERS = list(DownloadContentTypeFilter)


def _use_case() -> DownloadSinglePostUseCase:
    # The ctor only composes destination paths: the filter gate needs no context.
    return DownloadSinglePostUseCase(
        destination=Path('unused'),
        post_dto=cast('PostDTO', None),
        download_context=cast('DownloadContext', None),
    )


def _post_with(chunks: PostDataAllChunksList) -> Post:
    return Post(
        uuid='p1',
        title='post',
        created_at=NOW,
        updated_at=NOW,
        has_access=True,
        signed_query='',
        post_data_chunks=chunks,
    )


CHUNK_TO_FILTER = [
    (PostDataChunkFile(url='u', filename='f.zip'), DownloadContentTypeFilter.files),
    (PostDataChunkAudio(url='u', title='song'), DownloadContentTypeFilter.audio),
    (
        PostDataChunkBoostyVideo(id='v1', title='video', url='u', quality='high'),
        DownloadContentTypeFilter.boosty_videos,
    ),
    (PostDataChunkExternalVideo(url='u'), DownloadContentTypeFilter.external_videos),
    (PostDataChunkText(text_fragments=[]), DownloadContentTypeFilter.post_content),
    (PostDataChunkImage(url='u'), DownloadContentTypeFilter.post_content),
    (PostDataChunkTextualList(items=[]), DownloadContentTypeFilter.post_content),
]


@pytest.mark.parametrize(
    ('chunk', 'expected_filter'),
    CHUNK_TO_FILTER,
    ids=[type(chunk).__name__ for chunk, _ in CHUNK_TO_FILTER],
)
def test_chunk_answers_only_to_its_filter(
    chunk: PostDataAllChunks,
    expected_filter: DownloadContentTypeFilter,
):
    """A drifted mapping silently skips content or downloads what was filtered out."""
    use_case = _use_case()
    post = _post_with([chunk])
    for missing_part in DownloadContentTypeFilter:
        should_run = use_case._should_execute(post, [missing_part])
        assert should_run is (missing_part is expected_filter)


def test_post_without_chunks_is_skipped():
    """Nothing to download must mean "do not touch the disk at all"."""
    use_case = _use_case()
    assert use_case._should_execute(_post_with([]), ALL_FILTERS) is False


def test_one_missing_part_is_enough_to_execute():
    """A post with cached files but missing audio must still be processed."""
    use_case = _use_case()
    post = _post_with(
        [
            PostDataChunkFile(url='u', filename='f.zip'),
            PostDataChunkAudio(url='u', title='song'),
        ]
    )
    assert use_case._should_execute(post, [DownloadContentTypeFilter.audio]) is True


def test_fully_cached_post_is_skipped():
    """No missing parts must mean skip - or every cached post gets re-downloaded."""
    use_case = _use_case()
    post = _post_with([PostDataChunkFile(url='u', filename='f.zip')])
    assert use_case._should_execute(post, []) is False
