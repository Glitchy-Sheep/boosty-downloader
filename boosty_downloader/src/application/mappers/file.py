"""Mapping functions for converting API PostDataFile objects to domain PostDataChunkFile objects."""

from boosty_downloader.src.domain.post import PostDataChunkFile
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataFileDTO,
)


def to_domain_file_chunk(api_file: BoostyPostDataFileDTO) -> PostDataChunkFile:
    """Convert API PostDataFile to domain PostDataChunkFile."""
    return PostDataChunkFile(
        url=api_file.url,
        filename=api_file.title,
    )
