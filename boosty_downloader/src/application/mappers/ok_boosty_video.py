"""Mapper for converting Boosty API video DTOs to domain video content objects."""

from boosty_downloader.src.application.ok_video_ranking import (
    get_best_video,
)
from boosty_downloader.src.domain.post import PostDataChunkBoostyVideo
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataOkVideoDTO,
)
from boosty_downloader.src.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)


def to_ok_boosty_video_content(
    api_video_dto: BoostyPostDataOkVideoDTO, preferred_quality: BoostyOkVideoType
) -> PostDataChunkBoostyVideo | None:
    """
    Convert API video data to domain video content object.

    It uses the PostDataVideo DTO to extract the video URL and other metadata
    to create a domain video content object.
    """
    best_video_info = get_best_video(
        preferred_quality=preferred_quality,
        video_urls=api_video_dto.player_urls,
    )

    if best_video_info is None:
        return None

    best_video, choosed_quality = best_video_info

    return PostDataChunkBoostyVideo(
        url=best_video.url,
        title=api_video_dto.title,
        quality=choosed_quality.name,
    )
