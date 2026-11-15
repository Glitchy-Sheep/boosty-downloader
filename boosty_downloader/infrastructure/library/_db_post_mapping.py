"""Translate primary database rows and independent canonical post snapshots."""

from collections.abc import Sequence
from datetime import timedelta

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.stored_post import (
    MediaEntry,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library._db_models import DbMedia, DbPost
from boosty_downloader.infrastructure.library._post_text import post_body_text
from boosty_downloader.infrastructure.library._stored_validation import (
    validate_stored_post,
)
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError


def read_saved_post(row: DbPost, media: Sequence[DbMedia]) -> StoredPost:
    """Validate the complete saved generation, independent of its access overview."""
    if (
        row.saved_metadata is None
        or row.blocks is None
        or row.first_downloaded_at is None
        or row.synced_at is None
    ):
        message = 'Incomplete saved post generation in primary library'
        raise InvalidPostRecordError(message)
    sync = PostSync(row.first_downloaded_at, row.synced_at, row.page_template)
    if (
        row.origin != sync.origin
        or row.saved_metadata.author != row.author
        or row.saved_metadata.id != row.post_id
        or any(
            entry.author != row.author or entry.post_row_id != row.id for entry in media
        )
    ):
        message = 'Saved post identity disagrees with its primary library row'
        raise InvalidPostRecordError(message)
    inventory = {entry.media_id: _read_media_entry(entry) for entry in media}
    return validate_stored_post(
        StoredPost(row.saved_metadata, sync, row.blocks, inventory)
    )


def _read_media_entry(row: DbMedia) -> MediaEntry:
    return MediaEntry(
        kind=row.kind,
        status=row.status,
        added_at=row.added_at,
        position=row.position,
        removed_at=row.removed_at,
        path=row.path,
        size=row.size,
        title=row.title,
        filename=row.filename,
        artist=row.artist,
        duration=None if row.duration is None else timedelta(seconds=row.duration),
        width=row.width,
        height=row.height,
        preview_path=row.preview_path,
        error=row.error,
        thumbnail_path=row.thumbnail_path,
    )


def update_saved_post(row: DbPost, folder: str, record: StoredPost) -> None:
    """Update saved content while retaining an independent locked observation."""
    row.folder = folder
    row.saved_metadata = record.post
    row.blocks = record.blocks
    row.origin = record.sync.origin
    row.first_downloaded_at = record.sync.first_downloaded_at
    row.synced_at = record.sync.synced_at
    row.page_template = record.sync.page_template
    row.body_text = post_body_text(record)
    if row.access != PostAccess.locked:
        update_post_overview(row, record.post)


def update_post_overview(row: DbPost, post: PostMetadata) -> None:
    """Replace the effective overview independently of saved content and access."""
    row.url = post.url
    row.title = post.title
    row.created_at = post.created_at
    row.updated_at = post.updated_at
    row.published_at = post.published_at
    row.tier = post.tier
    row.tier_price_rub = post.tier_price_rub
    row.post_price_rub = post.post_price_rub
    row.likes = post.likes
    row.comments = post.comments
    row.tags = post.tags
    row.content_counters = post.content_counters


def update_media_entry(row: DbMedia, entry: MediaEntry) -> None:
    """Retain history and path bases exactly, including removed inventory entries."""
    row.kind = entry.kind
    row.status = entry.status
    row.position = entry.position
    row.path = entry.path
    row.thumbnail_path = entry.thumbnail_path
    row.preview_path = entry.preview_path
    row.title = entry.title
    row.filename = entry.filename
    row.artist = entry.artist
    row.size = entry.size
    row.duration = None if entry.duration is None else entry.duration.total_seconds()
    row.width = entry.width
    row.height = entry.height
    row.error = entry.error
    row.added_at = entry.added_at
    row.removed_at = entry.removed_at
