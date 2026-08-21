"""Mapping functions for converting audio API DTOs to domain objects."""

from boosty_downloader.domain.post_data_chunks import PostDataChunkAudio
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataAudioDTO,
)


def to_domain_audio_chunk(
    api_audio: BoostyPostDataAudioDTO, signed_query: str
) -> PostDataChunkAudio:
    """Convert API PostDataAudio to domain PostDataChunkAudio."""
    return PostDataChunkAudio(
        url=api_audio.url + signed_query,
        title=api_audio.title,
    )
