"""Keep remote access observations independent of downloaded post content."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from boosty_downloader.application.mappers.post_metadata import map_post_metadata
from boosty_downloader.domain.stored_post import LockedPost

if TYPE_CHECKING:
    from boosty_downloader.application.ports import PostStore
    from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO


def observe_post_access(store: PostStore, author: str, post: PostDTO) -> None:
    """Save a locked overview or clear it after confirmed access, without post writes."""
    if post.has_access:
        store.clear_locked_post(author, post.id)
        return
    store.save_locked_post(
        LockedPost(
            post=map_post_metadata(post, author),
            synced_at=datetime.now(timezone.utc),
        )
    )
