"""Mapping logic for converting Boosty API post DTOs to domain Post objects."""

from boosty_downloader.src.application import mappers
from boosty_downloader.src.application.download_manager.download_manager import (
    BoostyOkVideoType,
)
from boosty_downloader.src.domain.post import Post
from boosty_downloader.src.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.src.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataFileDTO,
    BoostyPostDataHeaderDTO,
    BoostyPostDataImageDTO,
    BoostyPostDataLinkDTO,
    BoostyPostDataListDTO,
    BoostyPostDataOkVideoDTO,
    BoostyPostDataTextDTO,
)


def map_post_dto_to_domain(post_dto: PostDTO) -> Post:
    """Convert a Boosty API PostDTO object to a domain Post object, mapping all data chunks to their domain representations."""
    post = Post(
        title=post_dto.title,
        created_at=post_dto.created_at,
        updated_at=post_dto.updated_at,
        has_access=post_dto.has_access,
        signed_query=post_dto.signed_query,
        post_data_chunks=[],
    )

    for data_chunk in post_dto.data:
        if isinstance(data_chunk, BoostyPostDataImageDTO):
            post.post_data_chunks.append(mappers.to_domain_image_chunk(data_chunk))
        elif isinstance(
            data_chunk,
            (BoostyPostDataTextDTO, BoostyPostDataHeaderDTO, BoostyPostDataLinkDTO),
        ):
            # Text-related DTOs return list of TextFragments, wrap in PostDataChunkText
            text_fragments = mappers.to_domain_text_chunk(data_chunk)
            text_chunk = PostDataChunkText(text_fragments=text_fragments)
            post.post_data_chunks.append(text_chunk)
        elif isinstance(data_chunk, BoostyPostDataListDTO):
            post.post_data_chunks.append(mappers.to_domain_list_chunk(data_chunk))
        elif isinstance(data_chunk, BoostyPostDataFileDTO):
            post.post_data_chunks.append(
                mappers.to_domain_file_chunk(data_chunk, post.signed_query)
            )
        elif isinstance(data_chunk, BoostyPostDataOkVideoDTO):
            # Try to get video content, skip if None (no suitable quality found)
            video_chunk = mappers.to_ok_boosty_video_content(
                data_chunk, preferred_quality=BoostyOkVideoType.high
            )
            if video_chunk is not None:
                post.post_data_chunks.append(video_chunk)
        else:
            # The only remaining type is BoostyPostDataExternalVideoDTO
            post.post_data_chunks.append(mappers.to_external_video_content(data_chunk))

    return post
