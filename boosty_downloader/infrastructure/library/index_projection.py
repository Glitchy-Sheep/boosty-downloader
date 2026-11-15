"""Typed index values derived from canonical library snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal

from boosty_downloader.domain.library_summary import latest_media_added_at
from boosty_downloader.domain.media_thumbnails import media_thumbnail_path
from boosty_downloader.domain.stored_post import (
    MediaBlock,
    MediaKind,
    MediaStatus,
)
from boosty_downloader.infrastructure.library._post_text import (
    fold_search_text,
    post_body_text,
    replace_search_controls,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from datetime import datetime

    from boosty_downloader.domain.library import PostAccess
    from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
    from boosty_downloader.domain.stored_post import (
        AuthorInfo,
        MediaEntry,
        PostMetadata,
        StoredPost,
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


def project_author(source: AuthorSource) -> AuthorProjection:
    """Retain author display metadata without sharing its mutable value objects."""
    return AuthorProjection(
        source.author,
        replace(source.info) if source.info is not None else None,
        source.author_fingerprint,
        source.locked_fingerprint,
    )


def project_post(source: PostSource) -> PostProjection:
    """Build independent query values while retaining canonical media states and sizes."""
    record = source.post.record
    media = _project_media(source)
    title = replace_search_controls(source.post.overview.post.title)
    text = replace_search_controls(post_body_text(record))
    return PostProjection(
        metadata=_copy_metadata(source.post.overview.post),
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
        pieces_added_at=latest_media_added_at(item.entry for item in media),
        marks=_copy_marks(source.marks),
        current_counts=_current_counts(media, downloaded_only=False),
        downloaded_counts=_current_counts(media, downloaded_only=True),
        media=media,
    )


def _copy_metadata(metadata: PostMetadata) -> PostMetadata:
    return replace(
        metadata,
        tags=list(metadata.tags),
        content_counters=dict(metadata.content_counters),
    )


def _copy_marks(marks: PostMarks) -> PostMarks:
    return replace(
        marks,
        positions={key: replace(value) for key, value in marks.positions.items()},
    )


def _copy_playback(playback: PlaybackPosition | None) -> PlaybackPosition | None:
    return replace(playback) if playback is not None else None


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
            replace(record.media[media_id]),
            position,
            media_thumbnail_path(record.post.author, folder, record.media[media_id]),
            _copy_playback(source.marks.positions.get(media_id)),
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
