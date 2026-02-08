"""Mapping logic for converting Boosty API post DTOs to domain Post objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from boosty_downloader.src.application import mappers
from boosty_downloader.src.application.filtering import DownloadContentTypeFilter
from boosty_downloader.src.domain.post import Post
from boosty_downloader.src.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.src.infrastructure.boosty_api.models.post.base_post_data import (
    BoostyPostDataExternalVideoDTO,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataAudioDTO,
    BoostyPostDataFileDTO,
    BoostyPostDataHeaderDTO,
    BoostyPostDataImageDTO,
    BoostyPostDataLinkDTO,
    BoostyPostDataListDTO,
    BoostyPostDataOkVideoDTO,
    BoostyPostDataTextDTO,
)

if TYPE_CHECKING:
    from boosty_downloader.src.infrastructure.boosty_api.models.post.post import (
        PostDTO,
    )
    from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
        BoostyOkVideoType,
    )


@dataclass
class PostMappingResult:
    """Result of mapping a PostDTO to a domain Post, including info about incomplete content."""

    post: Post
    incomplete_content_types: set[DownloadContentTypeFilter] = field(
        default_factory=lambda: set[DownloadContentTypeFilter]()
    )


def map_post_dto_to_domain(  # noqa: C901
    post_dto: PostDTO, preferred_video_quality: BoostyOkVideoType
) -> PostMappingResult:
    """Convert a Boosty API PostDTO object to a domain Post object, mapping all data chunks to their domain representations."""
    post = Post(
        uuid=post_dto.id,
        title=post_dto.title,
        created_at=post_dto.created_at,
        updated_at=post_dto.updated_at,
        has_access=post_dto.has_access,
        signed_query=post_dto.signed_query,
        post_data_chunks=[],
    )

    incomplete_content_types: set[DownloadContentTypeFilter] = set()

    for data_chunk in post_dto.data:
        match data_chunk:
            case BoostyPostDataImageDTO():
                post.post_data_chunks.append(mappers.to_domain_image_chunk(data_chunk))
            case (
                BoostyPostDataHeaderDTO()
                | BoostyPostDataLinkDTO()
                | BoostyPostDataTextDTO()
            ):
                text_fragments = mappers.to_domain_text_chunk(data_chunk)
                text_chunk = PostDataChunkText(text_fragments=text_fragments)
                post.post_data_chunks.append(text_chunk)
            case BoostyPostDataListDTO():
                post.post_data_chunks.append(mappers.to_domain_list_chunk(data_chunk))
            case BoostyPostDataFileDTO():
                post.post_data_chunks.append(
                    mappers.to_domain_file_chunk(data_chunk, post.signed_query)
                )
            case BoostyPostDataOkVideoDTO():
                if not data_chunk.complete:
                    incomplete_content_types.add(
                        DownloadContentTypeFilter.boosty_videos
                    )
                    continue
                video_chunk = mappers.to_ok_boosty_video_content(
                    data_chunk, preferred_quality=preferred_video_quality
                )
                if video_chunk is not None:
                    post.post_data_chunks.append(video_chunk)
            case BoostyPostDataExternalVideoDTO():
                post.post_data_chunks.append(
                    mappers.to_external_video_content(data_chunk)
                )
            case BoostyPostDataAudioDTO():
                if not data_chunk.complete:
                    incomplete_content_types.add(DownloadContentTypeFilter.audio)
                    continue
                post.post_data_chunks.append(mappers.to_domain_audio_chunk(data_chunk))

    return PostMappingResult(
        post=post,
        incomplete_content_types=incomplete_content_types,
    )
