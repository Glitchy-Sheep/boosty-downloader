"""Shared media responses for post details and playback writes."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.stored_post import MediaKind
from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.file_types import file_type
from boosty_downloader.viewer.media_identity import media_identity
from boosty_downloader.viewer.urls import post_media_path

if TYPE_CHECKING:
    from datetime import timedelta

    from boosty_downloader.domain.library_marks import PlaybackPosition
    from boosty_downloader.domain.library_mutations import LibraryMediaItem
    from boosty_downloader.domain.stored_post import MediaEntry


def media_item_response(author: str, item: LibraryMediaItem) -> api.MediaItem:
    """Keep media identity, stored paths and playback independent of rendered HTML."""
    entry = item.entry
    if entry.path is None or entry.size is None:
        message = 'A downloaded media record is incomplete.'
        raise LibraryReadError(message)
    return api.MediaItem(
        id=media_identity(item.post_id, item.media_id),
        post_id=item.post_id,
        created_at=item.created_at,
        kind=_wire_kind(entry.kind),
        path=post_media_path(author, item.folder, entry.path),
        thumb_path=_thumbnail(author, item.folder, entry),
        title=entry.title,
        filename=PurePosixPath(entry.path).name,
        artist=entry.artist,
        size=entry.size,
        width=entry.width,
        height=entry.height,
        duration_s=_duration_seconds(entry.duration),
        position_s=_playback_seconds(item.playback),
        finished=item.playback is not None and item.playback.finished_at is not None,
        file_type=file_type(PurePosixPath(entry.path).name),
        removed=entry.removed_at is not None,
    )


def _wire_kind(kind: MediaKind) -> api.MediaKind:
    match kind:
        case MediaKind.boosty_video | MediaKind.external_video:
            return 'videos'
        case MediaKind.audio:
            return 'audio'
        case MediaKind.file:
            return 'files'
        case MediaKind.image:
            return 'images'


def _thumbnail(author: str, folder: str, entry: MediaEntry) -> str | None:
    if entry.preview_path is None:
        return None
    return post_media_path(author, folder, entry.preview_path)


def _duration_seconds(duration: timedelta | None) -> float | None:
    match duration:
        case None:
            return None
        case _:
            return duration.total_seconds()


def _playback_seconds(playback: PlaybackPosition | None) -> float | None:
    match playback:
        case None:
            return None
        case _:
            return playback.seconds
