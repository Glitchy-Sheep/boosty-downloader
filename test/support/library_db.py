"""Canonical database fixtures with a frozen pre-search schema."""

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from sqlite3 import connect

from boosty_downloader.domain.library import PostAccess
from boosty_downloader.domain.stored_post import PostMetadata
from boosty_downloader.infrastructure.library._db_models import DbPost

NOW = datetime(2026, 10, 1, 11, 12, 13, 123456, tzinfo=timezone.utc)


def previous_database(path: Path) -> Path:
    path = path.resolve()
    fixture = Path(__file__).parents[1] / 'unit/library/fixtures/db_v1.sql'
    with closing(connect(path)) as connection:
        connection.executescript(fixture.read_text())
    return path


def saved_post(
    *,
    author: str = 'alice',
    post_id: str = 'full-id',
    title: str = 'Title',
    body: str = '',
) -> DbPost:
    metadata = PostMetadata(
        post_id, author, f'https://boosty.to/{author}/posts/{post_id}', title, NOW, NOW
    )
    return DbPost(
        author=author,
        post_id=post_id,
        folder=f'{author}/{post_id}',
        url=metadata.url,
        title=title,
        created_at=NOW,
        updated_at=NOW,
        access=PostAccess.open,
        saved_metadata=metadata,
        blocks=[],
        origin='api',
        first_downloaded_at=NOW,
        synced_at=NOW,
        body_text=body,
    )
