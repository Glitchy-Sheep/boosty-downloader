"""Mapping functions for converting external video API DTOs to domain objects."""

from boosty_downloader.src.domain.post import PostDataChunkExternalVideo
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataExternalVideoDTO,
)


def to_external_video_content(
    api_video_dto: BoostyPostDataExternalVideoDTO,
) -> PostDataChunkExternalVideo:
    """
    Convert API video data to domain external video content object.

    It uses the PostDataVideo DTO to extract the video URL and other metadata
    to create a domain external video content object.
    """
    return PostDataChunkExternalVideo(
        url=api_video_dto.url,
    )
