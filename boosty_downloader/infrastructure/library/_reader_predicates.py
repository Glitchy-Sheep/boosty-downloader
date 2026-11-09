"""Shared indexed predicates for post selections and author viewing counts."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Final

from sqlalchemy import and_, func, or_, select

from boosty_downloader.domain.library import LibraryContentKind, PostAccess
from boosty_downloader.domain.stored_post import MediaKind
from boosty_downloader.infrastructure.library._index_models import (
    IndexPost,
    IndexPostTag,
)

if TYPE_CHECKING:
    from sqlalchemy import ColumnElement

    from boosty_downloader.domain.library import PostFilters


class RemoteCounter(str, Enum):
    """Boosty content-counter names, distinct from stored media kinds."""

    platform_video = 'ok_video'
    external_video = 'video'
    image = 'image'
    file = 'file'
    audio = 'audio'


_SAVED_KINDS: Final = {
    LibraryContentKind.video: (MediaKind.boosty_video, MediaKind.external_video),
    LibraryContentKind.image: (MediaKind.image,),
    LibraryContentKind.file: (MediaKind.file,),
    LibraryContentKind.audio: (MediaKind.audio,),
}
_REMOTE_KINDS: Final = {
    LibraryContentKind.video: (
        RemoteCounter.platform_video,
        RemoteCounter.external_video,
    ),
    LibraryContentKind.image: (RemoteCounter.image,),
    LibraryContentKind.file: (RemoteCounter.file,),
    LibraryContentKind.audio: (RemoteCounter.audio,),
}


def post_predicates(author: str, filters: PostFilters) -> list[ColumnElement[bool]]:
    """Build metadata and media predicates shared by indexed post selections."""
    predicates: list[ColumnElement[bool]] = [IndexPost.author == author]
    if filters.tag is not None:
        predicates.append(_has_tag(filters.tag))
    if filters.kind is not None:
        predicates.append(_has_kind(filters.kind))
    if filters.unseen_only:
        predicates.append(is_unseen())
    if filters.favorites_only:
        predicates.append(IndexPost.favorite.is_(True))
    if filters.locked_only:
        predicates.append(IndexPost.access == PostAccess.locked.value)
    if filters.incomplete_only:
        predicates.append(_is_incomplete())
    return predicates


def is_unseen() -> ColumnElement[bool]:
    """Select open posts never seen or with pieces added after their last view."""
    return and_(
        IndexPost.access == PostAccess.open.value,
        or_(IndexPost.seen_at.is_(None), IndexPost.pieces_added_at > IndexPost.seen_at),
    )


def _has_tag(tag: str) -> ColumnElement[bool]:
    return (
        select(IndexPostTag.post_row_id)
        .where(IndexPostTag.post_row_id == IndexPost.id, IndexPostTag.tag == tag)
        .exists()
    )


def _has_kind(kind: LibraryContentKind) -> ColumnElement[bool]:
    saved = or_(
        *(
            func.coalesce(IndexPost.current_counts[item.value].as_integer(), 0) > 0
            for item in _SAVED_KINDS[kind]
        )
    )
    remote = or_(
        *(
            func.coalesce(IndexPost.content_counters[item.value].as_integer(), 0) > 0
            for item in _REMOTE_KINDS[kind]
        )
    )
    return or_(
        and_(IndexPost.folder.is_not(None), saved),
        and_(
            IndexPost.folder.is_(None),
            IndexPost.access == PostAccess.locked.value,
            remote,
        ),
    )


def _is_incomplete() -> ColumnElement[bool]:
    return and_(
        IndexPost.folder.is_not(None),
        or_(
            *(
                func.coalesce(IndexPost.current_counts[kind.value].as_integer(), 0)
                > func.coalesce(IndexPost.downloaded_counts[kind.value].as_integer(), 0)
                for kind in MediaKind
            )
        ),
    )
