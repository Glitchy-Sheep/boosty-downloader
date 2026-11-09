"""Build a complete HTTP post from one canonical content and marks snapshot."""

from __future__ import annotations

from functools import partial
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.library_summary import summarize_post
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.file_types import file_type
from boosty_downloader.viewer.mapping import post_response
from boosty_downloader.viewer.media_identity import media_identity
from boosty_downloader.viewer.media_paths import has_post_folder
from boosty_downloader.viewer.urls import media_url, post_media_path

if TYPE_CHECKING:
    from datetime import timedelta
    from pathlib import Path

    from boosty_downloader.application.ports import PostBodyRenderer
    from boosty_downloader.domain.library import LibraryPost, LibraryPostDetails
    from boosty_downloader.domain.library_marks import PlaybackPosition
    from boosty_downloader.domain.stored_post import MediaEntry


def post_detail_response(
    author: str, detail: LibraryPostDetails, root: Path, renderer: PostBodyRenderer
) -> api.PostDetail:
    """Render only this snapshot; no index refresh or extra mark reads are needed."""
    content = detail.content
    row = post_response(author, summarize_post(detail))
    post = content.overview.post
    return api.PostDetail(
        **row.model_dump(),
        tags=post.tags,
        tier_price_rub=post.tier_price_rub,
        post_price_rub=post.post_price_rub,
        boosty_url=post.url,
        body_html=_body_html(author, content, renderer),
        media=_detail_media(author, detail),
        has_folder=_has_folder(root, author, content.folder),
    )


def _has_folder(root: Path, author: str, folder: str | None) -> bool:
    match folder:
        case None:
            return False
        case _:
            return has_post_folder(root, author, folder)


def _body_media_url(author: str, folder: str, relative: str) -> str:
    return media_url(author, post_media_path(author, folder, relative))


def _body_html(author: str, content: LibraryPost, renderer: PostBodyRenderer) -> str:
    if content.record is None:
        return ''
    if content.folder is None:
        message = 'The saved post has no folder.'
        raise LibraryReadError(message)
    return renderer.render(
        content.record, media_url=partial(_body_media_url, author, content.folder)
    )


def _detail_media(author: str, detail: LibraryPostDetails) -> list[api.MediaItem]:
    content = detail.content
    if content.record is None:
        return []
    return [
        _media_item(author, detail, media_id, entry)
        for media_id, entry in sorted(
            content.record.media.items(),
            key=lambda item: (item[1].removed_at is not None, item[1].position),
        )
        if entry.status is MediaStatus.downloaded and entry.kind is not MediaKind.image
    ]


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


def _media_item(
    author: str, detail: LibraryPostDetails, key: str, entry: MediaEntry
) -> api.MediaItem:
    content = detail.content
    if content.folder is None or entry.path is None or entry.size is None:
        message = 'A downloaded media record is incomplete.'
        raise LibraryReadError(message)
    playback = detail.marks.positions.get(key)
    return api.MediaItem(
        id=media_identity(content.overview.post.id, key),
        post_id=content.overview.post.id,
        created_at=content.overview.post.created_at,
        kind=_wire_kind(entry.kind),
        path=post_media_path(author, content.folder, entry.path),
        thumb_path=_thumbnail(author, content.folder, entry),
        title=entry.title,
        filename=PurePosixPath(entry.path).name,
        artist=entry.artist,
        size=entry.size,
        width=entry.width,
        height=entry.height,
        duration_s=_duration_seconds(entry.duration),
        position_s=_playback_seconds(playback),
        finished=playback is not None and playback.finished_at is not None,
        file_type=file_type(PurePosixPath(entry.path).name),
        removed=entry.removed_at is not None,
    )


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
