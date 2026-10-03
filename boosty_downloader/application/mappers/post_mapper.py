"""Mapping logic for converting Boosty API post DTOs to domain Post objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from boosty_downloader.application import mappers
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post import Post, SubscriptionLevel
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.infrastructure.boosty_api.models.post.base_post_data import (
    BoostyPostDataExternalVideoDTO,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataAudioDTO,
    BoostyPostDataFileDTO,
    BoostyPostDataHeaderDTO,
    BoostyPostDataImageDTO,
    BoostyPostDataLinkDTO,
    BoostyPostDataListDTO,
    BoostyPostDataOkVideoDTO,
    BoostyPostDataTextDTO,
    BoostyPostDataUnknownDTO,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_overview import (
    PostCountDTO,
)

if TYPE_CHECKING:
    from boosty_downloader.infrastructure.boosty_api.models.post.post import (
        PostDTO,
    )
    from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
        BoostyOkVideoType,
    )


@dataclass
class PostMappingResult:
    """Result of mapping a PostDTO to a domain Post, including info about incomplete content."""

    post: Post
    incomplete_content_types: set[DownloadContentTypeFilter] = field(
        default_factory=set[DownloadContentTypeFilter]
    )
    # Titles of videos that offer only streaming manifests: skipped with
    # a warning and retried next run in case downloadable urls appear.
    stream_only_videos: list[str] = field(default_factory=list[str])


def _to_domain_post(post_dto: PostDTO) -> Post:
    """Build the domain post from the listing, without its chunks."""
    level = post_dto.subscription_level
    count = post_dto.count or PostCountDTO()
    return Post(
        uuid=post_dto.id,
        title=post_dto.title,
        created_at=post_dto.created_at,
        updated_at=post_dto.updated_at,
        has_access=post_dto.has_access,
        signed_query=post_dto.signed_query,
        post_data_chunks=[],
        published_at=post_dto.publish_time,
        tags=[tag.title for tag in post_dto.tags or []],
        teaser=[
            mappers.to_domain_image_chunk(image, post_dto.signed_query)
            for image in post_dto.teaser or []
        ],
        content_counters={
            counter.type: counter.count for counter in post_dto.content_counters or []
        },
        likes=count.likes,
        comments=count.comments,
        subscription_level=SubscriptionLevel(
            name=level.name, price=level.price, currency_prices=level.currency_prices
        )
        if level
        else None,
        price=post_dto.price,
        currency_prices=post_dto.currency_prices,
    )


def map_post_dto_to_domain(  # noqa: C901, PLR0912 - one match-dispatcher over every chunk type
    post_dto: PostDTO, preferred_video_quality: BoostyOkVideoType
) -> PostMappingResult:
    """Convert a Boosty API PostDTO object to a domain Post object, mapping all data chunks to their domain representations."""
    post = _to_domain_post(post_dto)

    incomplete_content_types: set[DownloadContentTypeFilter] = set()
    stream_only_videos: list[str] = []

    for data_chunk in post_dto.data:
        match data_chunk:
            case BoostyPostDataImageDTO():
                post.post_data_chunks.append(
                    mappers.to_domain_image_chunk(data_chunk, post.signed_query)
                )
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
                if not data_chunk.complete:
                    incomplete_content_types.add(DownloadContentTypeFilter.files)
                    continue
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
                elif any(u.url for u in data_chunk.player_urls):
                    # Streams may gain downloadable urls later: retry next run.
                    incomplete_content_types.add(
                        DownloadContentTypeFilter.boosty_videos
                    )
                    stream_only_videos.append(data_chunk.title)
            case BoostyPostDataExternalVideoDTO():
                post.post_data_chunks.append(
                    mappers.to_external_video_content(data_chunk)
                )
            case BoostyPostDataAudioDTO():
                if not data_chunk.complete:
                    incomplete_content_types.add(DownloadContentTypeFilter.audio)
                    continue
                post.post_data_chunks.append(
                    mappers.to_domain_audio_chunk(data_chunk, post.signed_query)
                )
            case BoostyPostDataUnknownDTO():
                # Reported by collect_unknown_content; nothing to map here.
                pass

    return PostMappingResult(
        post=post,
        incomplete_content_types=incomplete_content_types,
        stream_only_videos=stream_only_videos,
    )
