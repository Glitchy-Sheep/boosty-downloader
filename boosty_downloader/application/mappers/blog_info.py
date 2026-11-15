"""Author metadata with a complete plain-text blog description."""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

from boosty_downloader.application.mappers.link_header_text import to_domain_text_chunk
from boosty_downloader.application.mappers.list import to_domain_list_chunk
from boosty_downloader.domain.stored_post import AuthorInfo
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types import (
    BoostyPostDataHeaderDTO,
    BoostyPostDataLinkDTO,
    BoostyPostDataListDTO,
    BoostyPostDataTextDTO,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_text import (
    PARAGRAPH_END_MODIFIER,
)

if TYPE_CHECKING:
    from datetime import datetime

    from boosty_downloader.domain.post_data_chunks import PostDataChunkTextualList
    from boosty_downloader.infrastructure.boosty_api.models.blog import BlogInfoDTO
    from boosty_downloader.infrastructure.boosty_api.models.post.base_post_data import (
        BasePostData,
    )

_TextDTO: TypeAlias = (
    BoostyPostDataTextDTO | BoostyPostDataHeaderDTO | BoostyPostDataLinkDTO
)
_PARAGRAPH_BREAK = '\n\n'


def map_blog_info(dto: BlogInfoDTO, author: str, now: datetime) -> AuthorInfo:
    """Map descriptive fields; downloaded image paths belong to the run service."""
    return AuthorInfo(
        author=author,
        synced_at=now,
        title=dto.title,
        owner_name=dto.owner.name if dto.owner else None,
        description=_plain_description(dto.description),
        remote_post_count=dto.count.posts if dto.count else None,
    )


def _plain_description(chunks: list[BasePostData] | None) -> str | None:
    try:
        return _join_description(chunks)
    except (IndexError, KeyError, TypeError) as error:
        message = 'Blog description contains malformed text data'
        raise ValueError(message) from error


def _join_description(chunks: list[BasePostData] | None) -> str | None:
    description = ''
    follows_list = False
    for chunk in chunks or []:
        text = _plain_chunk(chunk)
        if not text:
            continue
        is_list = isinstance(chunk, BoostyPostDataListDTO)
        needs_boundary = is_list or follows_list
        has_boundary = description.endswith('\n') or text.startswith('\n')
        if description and needs_boundary and not has_boundary:
            description += _PARAGRAPH_BREAK
        description += text
        follows_list = is_list
    return description.strip() or None


def _plain_chunk(chunk: BasePostData) -> str:
    match chunk:
        case (
            BoostyPostDataTextDTO()
            | BoostyPostDataHeaderDTO()
            | BoostyPostDataLinkDTO()
        ):
            return _plain_text(chunk)
        case BoostyPostDataListDTO():
            listing = to_domain_list_chunk(chunk)
            return '\n'.join(_plain_list_item(item) for item in listing.items)
        case _:
            return ''


def _plain_text(chunk: _TextDTO) -> str:
    ends_paragraph = (
        isinstance(chunk, (BoostyPostDataTextDTO, BoostyPostDataHeaderDTO))
        and chunk.modificator == PARAGRAPH_END_MODIFIER
    )
    source = chunk.model_copy(update={'modificator': ''}) if ends_paragraph else chunk
    text = ''.join(fragment.text for fragment in to_domain_text_chunk(source))
    return text + _PARAGRAPH_BREAK if ends_paragraph else text


def _plain_list_item(item: PostDataChunkTextualList.ListItem) -> str:
    text = ''.join(
        fragment.text for chunk in item.data for fragment in chunk.text_fragments
    ).strip()
    nested = [_plain_list_item(child) for child in item.nested_items]
    return '\n'.join(part for part in [text, *nested] if part)
