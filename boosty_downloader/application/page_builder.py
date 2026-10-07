"""Build complete page content from a reconciled stored post without I/O."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from urllib.parse import quote

from boosty_downloader.application._page_text import (
    build_text_blocks,
    build_textual_list,
)
from boosty_downloader.application.mappers.html_converter import (
    convert_audio_to_html,
    convert_file_to_html,
    convert_video_to_html,
)
from boosty_downloader.domain.stored_post import (
    ListBlock,
    MediaBlock,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    TextBlock,
)
from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenDeleted,
    HtmlGenImage,
    HtmlGenNotDownloaded,
    HtmlGenRemovedMedia,
    HtmlGenUnavailable,
    UnavailableKind,
)

if TYPE_CHECKING:
    from boosty_downloader.domain.stored_post import (
        MediaEntry,
        StoredPost,
        TextContent,
    )
    from boosty_downloader.infrastructure.html_generator.models import (
        HtmlGenChunk,
        HtmlGenMedia,
    )


class InvalidStoredPostError(ValueError):
    """Stored content cannot be represented as a complete page."""


def build_post_page(record: StoredPost) -> list[HtmlGenChunk]:
    """
    Project current content and retained copies into independently owned page elements.

    The caller reconciles disk state first. A reserved path alone does not make a file downloaded. Rendering and recording the page template version belong to the caller.

    Raises:
        InvalidStoredPostError: A body reference is missing or downloaded media has no path.

    """
    chunks = _build_body(record)
    removed = _build_removed_media(record)
    if removed:
        chunks.append(HtmlGenRemovedMedia(media=removed))
    return chunks


def _build_body(record: StoredPost) -> list[HtmlGenChunk]:
    chunks: list[HtmlGenChunk] = []
    text: list[TextContent] = []
    for block in record.blocks:
        match block:
            case TextBlock() | ParagraphBreak():
                text.append(block)
            case ListBlock() | MediaBlock():
                chunks.extend(build_text_blocks(text))
                text.clear()
                chunks.append(_build_non_text(record, block))
    chunks.extend(build_text_blocks(text))
    return chunks


def _build_non_text(record: StoredPost, block: ListBlock | MediaBlock) -> HtmlGenChunk:
    match block:
        case ListBlock():
            return build_textual_list(block)
        case MediaBlock():
            entry = _get_media(record, block.media_id)
            return _build_current_media(block.media_id, entry, record.post.url)


def _get_media(record: StoredPost, media_id: str) -> MediaEntry:
    try:
        return record.media[media_id]
    except KeyError as error:
        message = f'Post content references missing media: {media_id}'
        raise InvalidStoredPostError(message) from error


def _build_current_media(
    media_id: str, entry: MediaEntry, post_url: str
) -> HtmlGenChunk:
    kind = _unavailable_kind(entry.kind)
    label = _media_label(media_id, entry)
    match entry.status:
        case MediaStatus.downloaded:
            return _build_saved_media(media_id, entry)
        case MediaStatus.pending:
            return HtmlGenNotDownloaded(
                kind=kind, label=label, duration=entry.duration, post_url=post_url
            )
        case MediaStatus.deleted:
            return HtmlGenDeleted(kind=kind, label=label)
        case MediaStatus.failed | MediaStatus.unavailable:
            return HtmlGenUnavailable(
                kind=kind,
                label=label,
                reason=entry.error or '',
                duration=entry.duration,
                source_url=_source_url(media_id, entry.kind),
            )


def _build_saved_media(media_id: str, entry: MediaEntry) -> HtmlGenMedia:
    if not entry.path:
        message = f'Downloaded media has no saved path: {media_id}'
        raise InvalidStoredPostError(message)
    src = quote(entry.path, safe='/')
    label = _media_label(media_id, entry)
    match entry.kind:
        case MediaKind.image:
            return HtmlGenImage(url=src, alt=PurePosixPath(entry.path).name)
        case MediaKind.file:
            return convert_file_to_html(src, filename=label, size=entry.size)
        case MediaKind.audio:
            return convert_audio_to_html(src, title=label)
        case MediaKind.boosty_video | MediaKind.external_video:
            return convert_video_to_html(src, title=label)


def _build_removed_media(record: StoredPost) -> list[HtmlGenMedia]:
    removed_ids = [
        media_id
        for media_id, entry in record.media.items()
        if entry.removed_at is not None and entry.status is MediaStatus.downloaded
    ]
    removed_ids.sort(key=lambda media_id: record.media[media_id].position)
    return [
        _build_saved_media(media_id, record.media[media_id]) for media_id in removed_ids
    ]


def _media_label(media_id: str, entry: MediaEntry) -> str:
    match entry.kind:
        case MediaKind.image:
            return ''
        case MediaKind.file:
            return entry.filename or _path_name(entry.path)
        case MediaKind.audio | MediaKind.boosty_video:
            return entry.title or _path_name(entry.path)
        case MediaKind.external_video:
            return (
                entry.title
                or _path_name(entry.path)
                or _source_url(media_id, entry.kind)
                or ''
            )


def _path_name(path: str | None) -> str:
    if not path:
        return ''
    return PurePosixPath(path).name


def _source_url(media_id: str, kind: MediaKind) -> str | None:
    if kind is MediaKind.external_video:
        return media_id.partition(':')[2]
    return None


def _unavailable_kind(kind: MediaKind) -> UnavailableKind:
    match kind:
        case MediaKind.image:
            return UnavailableKind.IMAGE
        case MediaKind.file:
            return UnavailableKind.FILE
        case MediaKind.audio:
            return UnavailableKind.AUDIO
        case MediaKind.boosty_video | MediaKind.external_video:
            return UnavailableKind.VIDEO
