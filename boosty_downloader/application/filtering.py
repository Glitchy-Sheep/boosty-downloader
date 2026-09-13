"""Content type filters for the download manager."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Final

from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from boosty_downloader.domain.post import Post


class VideoQualityOption(str, Enum):
    """Preferred video quality option for cli"""

    smallest_size = 'smallest_size'
    low = 'low'
    medium = 'medium'
    high = 'high'
    highest = 'highest'

    def to_ok_video_type(self) -> BoostyOkVideoType:
        mapping = {
            VideoQualityOption.smallest_size: BoostyOkVideoType.lowest,
            VideoQualityOption.low: BoostyOkVideoType.low,
            VideoQualityOption.medium: BoostyOkVideoType.medium,
            VideoQualityOption.high: BoostyOkVideoType.high,
            VideoQualityOption.highest: BoostyOkVideoType.ultra_hd,
        }
        return mapping[self]


# Which filter governs each domain chunk. Images render into the post page,
# so they belong to post_content, not to a filter of their own.
CHUNK_TO_FILTER: Final[dict[type, DownloadContentTypeFilter]] = {
    PostDataChunkAudio: DownloadContentTypeFilter.audio,
    PostDataChunkBoostyVideo: DownloadContentTypeFilter.boosty_videos,
    PostDataChunkExternalVideo: DownloadContentTypeFilter.external_videos,
    PostDataChunkFile: DownloadContentTypeFilter.files,
    PostDataChunkText: DownloadContentTypeFilter.post_content,
    PostDataChunkTextualList: DownloadContentTypeFilter.post_content,
    PostDataChunkImage: DownloadContentTypeFilter.post_content,
}


def post_has_content_for(
    post: Post, parts: Sequence[DownloadContentTypeFilter]
) -> bool:
    """Whether the post carries any content the given parts cover."""
    return any(
        CHUNK_TO_FILTER.get(type(chunk)) in parts for chunk in post.post_data_chunks
    )
