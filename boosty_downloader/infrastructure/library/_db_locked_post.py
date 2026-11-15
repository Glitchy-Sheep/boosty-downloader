"""Read validated locked observations independently of retained saved metadata."""

from boosty_downloader.domain.stored_post import LockedPost, PostMetadata
from boosty_downloader.infrastructure.library._author_validation import (
    validate_locked_snapshot,
)
from boosty_downloader.infrastructure.library._db_models import DbPost
from boosty_downloader.infrastructure.library.errors import InvalidAuthorRecordError


def read_locked_post(row: DbPost) -> LockedPost:
    """Return an independent access snapshot, including its original observation clock."""
    if row.locked_synced_at is None:
        message = 'Locked overview has no synchronization time'
        raise InvalidAuthorRecordError(message)
    return validate_locked_snapshot(
        LockedPost(
            _read_overview(row),
            row.locked_synced_at,
            teaser_path=row.teaser_path,
            teaser_thumbnail_path=row.teaser_thumbnail_path,
        )
    )


def _read_overview(row: DbPost) -> PostMetadata:
    return PostMetadata(
        id=row.post_id,
        author=row.author,
        url=row.url,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
        published_at=row.published_at,
        tags=row.tags,
        tier=row.tier,
        tier_price_rub=row.tier_price_rub,
        post_price_rub=row.post_price_rub,
        likes=row.likes,
        comments=row.comments,
        content_counters=row.content_counters,
    )
