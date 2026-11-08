"""Typed index values derived from canonical library snapshots."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, Literal

from boosty_downloader.domain.stored_post import (
    LineBreak,
    ListBlock,
    MediaBlock,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    TextBlock,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from boosty_downloader.domain.library import PostAccess
    from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
    from boosty_downloader.domain.stored_post import (
        AuthorInfo,
        Block,
        ListItem,
        MediaEntry,
        PostMetadata,
        StoredPost,
        TextContent,
    )
    from boosty_downloader.infrastructure.library.index_sources import (
        AuthorSource,
        PostSource,
        SourceFingerprint,
    )


@dataclass(frozen=True, slots=True)
class AuthorProjection:
    """Author metadata and the source versions used to build its indexed rows."""

    author: str
    info: AuthorInfo | None
    author_fingerprint: SourceFingerprint | None
    locked_fingerprint: SourceFingerprint | None


@dataclass(frozen=True, slots=True)
class MediaProjection:
    """Post-relative entry paths, a library-relative thumbnail and saved playback."""

    media_id: str
    entry: MediaEntry
    position: int
    thumbnail_path: str | None
    playback: PlaybackPosition | None


@dataclass(frozen=True, slots=True)
class PostProjection:
    """Canonical query values; folder/cover are library-relative, teaser author-relative."""

    metadata: PostMetadata
    access: PostAccess
    folder: str | None
    teaser_path: str | None
    record_fingerprint: SourceFingerprint | None
    marks_fingerprint: SourceFingerprint | None
    cover_path: str | None
    origin: Literal['api', 'locked']
    title: str
    text: str
    title_folded: str
    text_folded: str
    excerpt: str
    pieces_added_at: datetime | None
    marks: PostMarks
    current_counts: dict[MediaKind, int]
    downloaded_counts: dict[MediaKind, int]
    media: tuple[MediaProjection, ...]


_EXCERPT_LENGTH: Final = 240
_HIT_MARKERS: Final = str.maketrans({'\x02': ' ', '\x03': ' '})
_RUSSIAN_FOLD: Final = str.maketrans({'ё': 'е', 'Ё': 'Е'})


def project_author(source: AuthorSource) -> AuthorProjection:
    """Retain author display metadata without sharing its mutable value objects."""
    return AuthorProjection(
        source.author,
        deepcopy(source.info),
        source.author_fingerprint,
        source.locked_fingerprint,
    )


def project_post(source: PostSource) -> PostProjection:
    """Build independent query values while retaining canonical media states and sizes."""
    record = source.post.record
    media = _project_media(source)
    title = source.post.overview.post.title.translate(_HIT_MARKERS)
    text = _body_text(record).translate(_HIT_MARKERS)
    return PostProjection(
        metadata=deepcopy(source.post.overview.post),
        access=source.post.overview.access,
        folder=source.post.folder,
        teaser_path=source.post.teaser_path,
        record_fingerprint=source.record_fingerprint,
        marks_fingerprint=source.marks_fingerprint,
        cover_path=source.cover_path,
        origin='api' if record is not None else 'locked',
        title=title,
        text=text,
        title_folded=fold_search_text(title),
        text_folded=fold_search_text(text),
        excerpt=' '.join(text.split())[:_EXCERPT_LENGTH],
        pieces_added_at=_pieces_added_at(media),
        marks=deepcopy(source.marks),
        current_counts=_current_counts(media, downloaded_only=False),
        downloaded_counts=_current_counts(media, downloaded_only=True),
        media=media,
    )


def fold_search_text(text: str) -> str:
    """Fold Russian yo without changing offsets; FTS handles case and Latin accents."""
    return text.translate(_HIT_MARKERS).translate(_RUSSIAN_FOLD)


def _project_media(source: PostSource) -> tuple[MediaProjection, ...]:
    record = source.post.record
    if record is None:
        return ()
    folder = source.post.folder
    if folder is None:
        message = 'A saved record requires its library-relative post folder'
        raise ValueError(message)
    return tuple(
        MediaProjection(
            media_id,
            deepcopy(record.media[media_id]),
            position,
            _thumbnail_path(folder, record.media[media_id]),
            deepcopy(source.marks.positions.get(media_id)),
        )
        for position, media_id in enumerate(_ordered_media_ids(record))
    )


def _ordered_media_ids(record: StoredPost) -> Iterator[str]:
    seen: set[str] = set()
    for block in record.blocks:
        if (
            isinstance(block, MediaBlock)
            and block.media_id not in seen
            and record.media[block.media_id].removed_at is None
        ):
            seen.add(block.media_id)
            yield block.media_id
    retained = sorted(record.media.items(), key=lambda item: item[1].position)
    for media_id, entry in retained:
        if entry.removed_at is None and media_id not in seen:
            yield media_id
    for media_id, entry in retained:
        if entry.removed_at is not None:
            yield media_id


def _thumbnail_path(folder: str, entry: MediaEntry) -> str | None:
    match entry.kind:
        case MediaKind.image if entry.status is MediaStatus.downloaded:
            path = entry.path
        case MediaKind.boosty_video | MediaKind.external_video:
            path = entry.preview_path
        case _:
            path = None
    return (PurePosixPath(folder) / path).as_posix() if path is not None else None


def _pieces_added_at(media: tuple[MediaProjection, ...]) -> datetime | None:
    return max(
        (
            item.entry.added_at
            for item in media
            if item.entry.removed_at is None
            or item.entry.status is MediaStatus.downloaded
        ),
        default=None,
    )


def _current_counts(
    media: tuple[MediaProjection, ...], *, downloaded_only: bool
) -> dict[MediaKind, int]:
    counts = dict.fromkeys(MediaKind, 0)
    for item in media:
        entry = item.entry
        if entry.removed_at is None and (
            not downloaded_only or entry.status is MediaStatus.downloaded
        ):
            counts[entry.kind] += 1
    return counts


def _body_text(record: StoredPost | None) -> str:
    if record is None:
        return ''
    return ''.join(_block_text(block) for block in record.blocks).strip()


def _block_text(block: Block) -> str:
    match block:
        case TextBlock() | ParagraphBreak():
            return _text_content(block)
        case ListBlock():
            return '\n'.join(_list_item_text(item) for item in block.items) + '\n'
        case MediaBlock():
            return '\n'


def _text_content(block: TextContent) -> str:
    match block:
        case ParagraphBreak():
            return '\n\n'
        case TextBlock():
            return ''.join(
                '\n' if isinstance(fragment, LineBreak) else fragment.text
                for fragment in block.fragments
            )


def _list_item_text(item: ListItem) -> str:
    own_text = ''.join(_text_content(block) for block in item.data)
    return '\n'.join(
        [own_text, *(_list_item_text(nested) for nested in item.nested_items)]
    )
