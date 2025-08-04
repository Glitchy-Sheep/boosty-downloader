"""Image content mapper module to transform Boosty API DTO to domain model."""

from boosty_downloader.src.domain.post import PostDataChunkImage
from boosty_downloader.src.infrastructure.boosty_api.models.post.base_post_data import (
    BoostyPostDataImageDTO,
)


def to_domain_image_chunk(api_image: BoostyPostDataImageDTO) -> PostDataChunkImage:
    """Convert API PostDataImage to domain PostDataChunkImage."""
    return PostDataChunkImage(
        url=api_image.url,
    )
