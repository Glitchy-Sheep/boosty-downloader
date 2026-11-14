"""Build a complete HTTP post from one canonical content and marks snapshot."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from boosty_downloader.application.post_links import ViewerPostLinks
from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.library_media import LibraryMediaItem
from boosty_downloader.domain.library_summary import summarize_post
from boosty_downloader.domain.media_thumbnails import media_thumbnail_path
from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.mapping import post_response
from boosty_downloader.viewer.media_mapping import media_item_response
from boosty_downloader.viewer.media_paths import has_post_folder
from boosty_downloader.viewer.urls import media_url, post_media_path

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import LinkResolver, PostBodyRenderer
    from boosty_downloader.domain.library import LibraryPost, LibraryPostDetails
    from boosty_downloader.domain.stored_post import MediaEntry


def post_detail_response(
    author: str,
    detail: LibraryPostDetails,
    root: Path,
    renderer: PostBodyRenderer,
    *,
    link_resolver: LinkResolver | None = None,
) -> api.PostDetail:
    """Render this source snapshot and resolve links without refreshing the index."""
    content = detail.content
    row = post_response(author, summarize_post(detail))
    post = content.overview.post
    return api.PostDetail(
        **row.model_dump(),
        tags=post.tags,
        tier_price_rub=post.tier_price_rub,
        post_price_rub=post.post_price_rub,
        boosty_url=post.url,
        body_html=_body_html(author, content, renderer, link_resolver),
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


def _body_html(
    author: str,
    content: LibraryPost,
    renderer: PostBodyRenderer,
    link_resolver: LinkResolver | None,
) -> str:
    if content.record is None:
        return ''
    if content.folder is None:
        message = 'The saved post has no folder.'
        raise LibraryReadError(message)
    links = None
    if link_resolver is not None:
        links = ViewerPostLinks(link_resolver)
    return renderer.render(
        content.record,
        media_url=partial(_body_media_url, author, content.folder),
        link_url=links,
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


def _media_item(
    author: str, detail: LibraryPostDetails, key: str, entry: MediaEntry
) -> api.MediaItem:
    content = detail.content
    if content.folder is None:
        message = 'A downloaded media record has no folder.'
        raise LibraryReadError(message)
    item = LibraryMediaItem(
        post_id=content.overview.post.id,
        created_at=content.overview.post.created_at,
        folder=content.folder,
        media_id=key,
        entry=entry,
        playback=detail.marks.positions.get(key),
        thumbnail_path=media_thumbnail_path(author, content.folder, entry),
    )
    return media_item_response(author, item)
