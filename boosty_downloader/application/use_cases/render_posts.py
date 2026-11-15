"""Rebuild saved post pages from canonical content and current local files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from boosty_downloader.application.post_link_tracker import (
    PostLinkTracker,
    PostPageLocation,
)
from boosty_downloader.application.post_pages import render_post_page
from boosty_downloader.application.reconcile import observe_recorded_files
from boosty_downloader.domain.library import PostIdentity, SavedPost
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.media_snapshot import read_media_snapshot

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import LinkResolver, StoredPostCollection
    from boosty_downloader.domain.stored_post import StoredPost


@dataclass(frozen=True, slots=True)
class RenderReport:
    """Pages successfully rebuilt from saved records."""

    pages: int


class RenderPostsUseCase:
    """Render saved bodies without network, index or viewing-state dependencies."""

    def __init__(
        self,
        library_root: Path,
        store: StoredPostCollection,
        *,
        link_resolver: LinkResolver,
    ) -> None:
        self._root = library_root
        self._store = store
        self._link_resolver = link_resolver

    def execute(self, author: str | None = None) -> RenderReport:
        """Rebuild each selected saved page; propagate failures without a success report."""
        pages = 0
        tracker = PostLinkTracker()
        for saved in self._store.iter_saved_posts(author):
            self._render_post(saved, tracker)
            pages += 1
        self._refresh_links(tracker)
        return RenderReport(pages=pages)

    def _render_post(self, saved: SavedPost, tracker: PostLinkTracker) -> None:
        record = _observe_local_media(self._root, saved)
        result = render_post_page(
            record,
            root=self._root,
            folder=saved.folder,
            link_resolver=self._link_resolver,
        )
        record.sync.page_template = PAGE_TEMPLATE_VERSION
        if record != saved.record:
            self._store.save_post(saved.folder, record)
        location = PostPageLocation(
            PostIdentity(record.post.author, record.post.id), saved.folder
        )
        tracker.record_render(location, result.unresolved)

    def _refresh_links(self, tracker: PostLinkTracker) -> None:
        for location in tracker.ready_sources():
            self._render_post(self._find_saved_post(location.identity), tracker)

    def _find_saved_post(self, identity: PostIdentity) -> SavedPost:
        located = self._store.find_post(identity.author, identity.post_id)
        if located is None or located.record is None:
            message = (
                'Saved post disappeared while refreshing links: '
                f'{identity.author}/{identity.post_id}'
            )
            raise ValueError(message)
        current = located.record.post
        if PostIdentity(current.author, current.id) != identity:
            message = (
                'Saved post identity changed while refreshing links: '
                f'{identity.author}/{identity.post_id}'
            )
            raise ValueError(message)
        return SavedPost(located.folder, located.record)


def _observe_local_media(root: Path, saved: SavedPost) -> StoredPost:
    paths = [
        entry.path for entry in saved.record.media.values() if entry.path is not None
    ]
    disk = read_media_snapshot(root, saved.folder, queried_paths=paths)
    return observe_recorded_files(saved.record, disk)
