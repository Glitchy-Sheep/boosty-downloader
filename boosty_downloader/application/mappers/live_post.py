"""
A complete live post for comparing API content with a saved library record.

Unfinished media keeps its identity and place in the body. Download links belong to this temporary input; local paths and file history belong to StoredPost.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypeAlias

from boosty_downloader.application import mappers
from boosty_downloader.application.mappers.list import to_domain_list_style
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
    PostDataChunkText,
)
from boosty_downloader.domain.stored_post import (
    Block,
    LineBreak,
    ListBlock,
    ListItem,
    MediaBlock,
    MediaKind,
    ParagraphBreak,
    PostMetadata,
    TextBlock,
    TextContent,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataAudioDTO,
    BoostyPostDataExternalVideoDTO,
    BoostyPostDataFileDTO,
    BoostyPostDataHeaderDTO,
    BoostyPostDataImageDTO,
    BoostyPostDataLinkDTO,
    BoostyPostDataListDTO,
    BoostyPostDataOkVideoDTO,
    BoostyPostDataTextDTO,
    BoostyPostDataUnknownDTO,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_list import (
    BoostyListItemType,
    BoostyPostDataListItemDTO,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_text import (
    PARAGRAPH_END_MODIFIER,
)

if TYPE_CHECKING:
    from datetime import timedelta

    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
    from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
        BoostyOkVideoType,
    )


_TextDTO: TypeAlias = (
    BoostyPostDataTextDTO | BoostyPostDataHeaderDTO | BoostyPostDataLinkDTO
)
DownloadableMediaChunk: TypeAlias = (
    PostDataChunkImage
    | PostDataChunkFile
    | PostDataChunkAudio
    | PostDataChunkBoostyVideo
    | PostDataChunkExternalVideo
)
_MediaDTO: TypeAlias = (
    BoostyPostDataImageDTO
    | BoostyPostDataFileDTO
    | BoostyPostDataAudioDTO
    | BoostyPostDataOkVideoDTO
    | BoostyPostDataExternalVideoDTO
)


@dataclass
class LiveMedia:
    """A present piece, including media that is not ready to download."""

    kind: MediaKind
    download: DownloadableMediaChunk | None
    # API estimate in bytes; StoredPost records actual disk bytes separately.
    expected_size: int | None = None
    title: str | None = None
    filename: str | None = None
    artist: str | None = None
    duration: timedelta | None = None
    width: int | None = None
    height: int | None = None
    preview_url: str | None = None


@dataclass
class LivePost:
    """Current post metadata and its complete supported body, before local state."""

    post: PostMetadata
    has_access: bool
    blocks: list[Block]
    media: dict[str, LiveMedia]


def map_post_dto_to_live(
    post_dto: PostDTO,
    author: str,
    preferred_video_quality: BoostyOkVideoType,
) -> LivePost:
    """Keep every supported piece, including those without a download yet."""
    live = LivePost(_map_metadata(post_dto, author), post_dto.has_access, [], {})
    for chunk in post_dto.data:
        match chunk:
            case (
                BoostyPostDataTextDTO()
                | BoostyPostDataHeaderDTO()
                | BoostyPostDataLinkDTO()
            ):
                live.blocks.extend(_map_text(chunk))
            case BoostyPostDataListDTO():
                live.blocks.append(
                    ListBlock(
                        [_map_list_item(item) for item in chunk.items],
                        to_domain_list_style(chunk.style),
                    )
                )
            case (
                BoostyPostDataImageDTO()
                | BoostyPostDataFileDTO()
                | BoostyPostDataAudioDTO()
                | BoostyPostDataOkVideoDTO()
                | BoostyPostDataExternalVideoDTO()
            ):
                media = _map_media(
                    chunk, post_dto.signed_query, preferred_video_quality
                )
                source_id = (
                    chunk.url
                    if isinstance(chunk, BoostyPostDataExternalVideoDTO)
                    else chunk.id
                )
                media_id = f'{media.kind.value}:{source_id}'
                live.media[media_id] = media
                live.blocks.append(MediaBlock(media_id))
            case BoostyPostDataUnknownDTO():
                # Unsupported chunks are reported from the API response.
                pass
    return live


def _map_metadata(post: PostDTO, author: str) -> PostMetadata:
    tier = post.subscription_level
    return PostMetadata(
        id=post.id,
        author=author,
        url=f'https://boosty.to/{author}/posts/{post.id}',
        title=post.title,
        created_at=post.created_at,
        updated_at=post.updated_at,
        published_at=post.publish_time,
        tags=[tag.title for tag in post.tags or []],
        tier=tier.name if tier else None,
        tier_price_rub=_rub_price(tier.currency_prices) if tier else None,
        post_price_rub=_rub_price(post.currency_prices),
        likes=post.count.likes if post.count else 0,
        comments=post.count.comments if post.count else 0,
        content_counters={
            item.type: item.count for item in post.content_counters or []
        },
    )


def _rub_price(prices: dict[str, float] | None) -> float | None:
    return prices.get('RUB') if prices is not None else None


def _to_text_block(fragments: list[PostDataChunkText.TextFragment]) -> TextBlock:
    result: list[PostDataChunkText.TextFragment | LineBreak] = []
    for index, fragment in enumerate(fragments):
        text = fragment.text
        next_text = fragments[index + 1].text if index + 1 < len(fragments) else ''
        # CRLF is one break even when its characters have different styles.
        if text.endswith('\r') and next_text == '\n':
            text = text[:-1]
            if not text:
                continue
        result.append(
            LineBreak()
            if text in ('\n', '\r\n')
            else replace(fragment, text=text, style=replace(fragment.style))
        )
    return TextBlock(result)


def _map_text(chunk: _TextDTO) -> list[TextContent]:
    ends_paragraph = (
        isinstance(chunk, (BoostyPostDataTextDTO, BoostyPostDataHeaderDTO))
        and chunk.modificator == PARAGRAPH_END_MODIFIER
    )
    # Paragraph boundaries must survive separately from inline line breaks.
    source = chunk.model_copy(update={'modificator': ''}) if ends_paragraph else chunk
    text = _to_text_block(mappers.to_domain_text_chunk(source))
    result: list[TextContent] = [text] if text.fragments or not ends_paragraph else []
    if ends_paragraph:
        result.append(ParagraphBreak())
    return result


def _map_list_item(item: BoostyPostDataListItemDTO) -> ListItem:
    data: list[TextContent] = []
    for chunk in item.data:
        if chunk.type is BoostyListItemType.text:
            data.extend(
                _map_text(
                    BoostyPostDataTextDTO(
                        type='text',
                        content=chunk.content,
                        modificator=chunk.modificator or '',
                    )
                )
            )
    return ListItem(data, [_map_list_item(nested) for nested in item.items])


def _map_media(
    chunk: _MediaDTO, signed_query: str, preferred_quality: BoostyOkVideoType
) -> LiveMedia:
    match chunk:
        case BoostyPostDataImageDTO():
            return _map_image(chunk, signed_query)
        case BoostyPostDataFileDTO():
            return _map_file(chunk, signed_query)
        case BoostyPostDataAudioDTO():
            return _map_audio(chunk, signed_query)
        case BoostyPostDataOkVideoDTO():
            return _map_video(chunk, preferred_quality)
        case BoostyPostDataExternalVideoDTO():
            return LiveMedia(
                MediaKind.external_video, mappers.to_external_video_content(chunk)
            )


def _map_image(chunk: BoostyPostDataImageDTO, signed_query: str) -> LiveMedia:
    return LiveMedia(
        kind=MediaKind.image,
        download=mappers.to_domain_image_chunk(chunk, signed_query),
        expected_size=chunk.size,
        width=chunk.width,
        height=chunk.height,
    )


def _map_file(chunk: BoostyPostDataFileDTO, signed_query: str) -> LiveMedia:
    return LiveMedia(
        kind=MediaKind.file,
        download=mappers.to_domain_file_chunk(chunk, signed_query)
        if chunk.complete
        else None,
        expected_size=chunk.size,
        filename=chunk.title,
    )


def _map_audio(chunk: BoostyPostDataAudioDTO, signed_query: str) -> LiveMedia:
    return LiveMedia(
        kind=MediaKind.audio,
        download=mappers.to_domain_audio_chunk(chunk, signed_query)
        if chunk.complete
        else None,
        expected_size=chunk.size,
        title=chunk.title,
        artist=chunk.artist,
        duration=chunk.duration,
    )


def _map_video(
    chunk: BoostyPostDataOkVideoDTO, preferred_quality: BoostyOkVideoType
) -> LiveMedia:
    return LiveMedia(
        kind=MediaKind.boosty_video,
        download=mappers.to_ok_boosty_video_content(chunk, preferred_quality)
        if chunk.complete
        else None,
        title=chunk.title,
        duration=chunk.duration,
        preview_url=chunk.preview or None,
    )
