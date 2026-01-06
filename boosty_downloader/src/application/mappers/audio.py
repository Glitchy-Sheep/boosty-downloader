"""Mapping functions for converting audio API DTOs to domain objects."""

from boosty_downloader.src.domain.post_data_chunks import PostDataChunkAudio
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataAudioDTO,
)


def to_domain_audio_chunk(
    api_audio: BoostyPostDataAudioDTO,
) -> PostDataChunkAudio:
    """Convert API PostDataAudio to domain PostDataChunkAudio."""
    return PostDataChunkAudio(
        url=api_audio.url,
        title=api_audio.title,
    )
