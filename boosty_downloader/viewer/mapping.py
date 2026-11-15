"""Map storage-neutral library snapshots into the viewer's JSON contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from boosty_downloader.viewer import api_models as api
from boosty_downloader.viewer.urls import author_relative_path, media_url

if TYPE_CHECKING:
    from boosty_downloader.domain.library import (
        LibraryAuthor,
        PostList,
        PostRow,
        SearchMatch,
    )


@dataclass(frozen=True, slots=True)
class _AuthorDisplay:
    title: str = ''
    description: str = ''
    avatar_url: str | None = None
    cover_url: str | None = None


def _author_display(author: LibraryAuthor) -> _AuthorDisplay:
    info = author.info
    if info is None:
        return _AuthorDisplay()
    return _AuthorDisplay(
        title=info.title or '',
        description=info.description or '',
        avatar_url=_artwork_url(author.author, info.avatar_path),
        cover_url=_artwork_url(author.author, info.cover_path),
    )


def author_response(author: LibraryAuthor) -> api.Author:
    """Use indexed totals without another read for each author."""
    display = _author_display(author)
    return api.Author(
        name=author.author,
        title=display.title,
        description=display.description,
        avatar_url=display.avatar_url,
        cover_url=display.cover_url,
        posts=author.counts.posts,
        locked=author.counts.locked,
        unseen=author.counts.unseen,
        favorites=author.counts.favorites,
        storage=api.MediaStorage.model_validate(author.storage, from_attributes=True),
    )


def _artwork_url(author: str, path: str | None) -> str | None:
    match path:
        case None:
            return None
        case _:
            return media_url(author, path)


def post_response(author: str, row: PostRow) -> api.PostRow:
    """Retain saved marks and show whether content arrived after the seen time."""
    post = row.overview.post
    return api.PostRow(
        id=post.id,
        title=post.title,
        created_at=post.created_at,
        access=row.overview.access.value,
        tier=post.tier,
        cover_path=author_relative_path(author, row.cover_path),
        counts=api.MediaCounts.model_validate(row.counts, from_attributes=True),
        missing_media=row.missing_media,
        seen=row.seen_at is not None,
        favorite=row.favorite,
        updated=is_updated(row),
        match=_search_match(row.match),
    )


def is_updated(row: PostRow) -> bool:
    """Check for pieces added after the retained seen mark."""
    return (
        row.seen_at is not None
        and row.pieces_added_at is not None
        and row.pieces_added_at > row.seen_at
    )


def _search_match(match: SearchMatch | None) -> api.SearchMatch | None:
    if match is None:
        return None
    body = None
    if match.text is not None:
        body = [api.SearchRun(text=run.text, matched=run.matched) for run in match.text]
    return api.SearchMatch(
        title=[
            api.SearchRun(text=run.text, matched=run.matched) for run in match.title
        ],
        text=body,
    )


def posts_response(author: str, posts: PostList) -> api.PostList:
    """Return rows, months and total from the reader's same filtered selection."""
    return api.PostList(
        rows=[post_response(author, row) for row in posts.rows],
        months=[
            api.MonthCount(month=item.month, count=item.count) for item in posts.months
        ],
        total=posts.total,
    )
