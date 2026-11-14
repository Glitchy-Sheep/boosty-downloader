"""Predict final page links and folder ownership without publishing anything."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.post_link_tracker import PostPageLocation
from boosty_downloader.application.post_links import has_post_links
from boosty_downloader.application.post_pages import prepare_post_page
from boosty_downloader.domain.library import PostIdentity
from boosty_downloader.infrastructure.html_generator.renderer import page_matches
from boosty_downloader.infrastructure.library.page_links import (
    SavedPageLinkResolver,
    is_linkable_page_folder,
)
from boosty_downloader.infrastructure.media_output_paths import (
    resolve_media_destination,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import PostLocator
    from boosty_downloader.application.post_preparation import PreparedPost
    from boosty_downloader.domain.stored_post import StoredPost


class PlannedPostPages:
    """Compare cached sources against targets available after normal completion."""

    def __init__(self, root: Path, locator: PostLocator) -> None:
        self._root = root
        self._locator = locator
        self._existing = SavedPageLinkResolver(root, locator.find_post)
        self._targets: dict[PostIdentity, str] = {}
        self._sources: dict[PostIdentity, PostPageLocation] = {}

    def record(self, prepared: PreparedPost) -> None:
        """Remember future publications and otherwise cached linked sources."""
        post = prepared.live.post
        identity = PostIdentity(post.author, post.id)
        if prepared.needs_update:
            self._targets[identity] = prepared.folder
        elif prepared.stored is not None and has_post_links(prepared.stored):
            self._sources[identity] = PostPageLocation(identity, prepared.folder)

    def post_folder(self, author: str, post_id: str) -> str | None:
        """Use prospective targets only where an ordinary page can be linked."""
        folder = self._targets.get(PostIdentity(author, post_id))
        if folder is None:
            return self._existing.post_folder(author, post_id)
        if is_linkable_page_folder(self._root, folder, allow_missing=True):
            return folder
        return None

    def count_updated_sources(self) -> int:
        """Read final canonical sources afresh; comparisons never write files."""
        return sum(self._page_changed(source) for source in self._sources.values())

    def _page_changed(self, source: PostPageLocation) -> bool:
        record = self._read_source(source)
        page = prepare_post_page(record, folder=source.folder, link_resolver=self)
        path = resolve_media_destination(self._root, source.folder, 'post.html')
        return not page_matches(path, page.content)

    def _read_source(self, source: PostPageLocation) -> StoredPost:
        identity = source.identity
        located = self._locator.find_post(identity.author, identity.post_id)
        if (
            located is None
            or located.record is None
            or located.folder != source.folder
            or located.record.post.author != identity.author
            or located.record.post.id != identity.post_id
        ):
            message = (
                f'Saved post changed before planning its links: {identity.post_id}'
            )
            raise ValueError(message)
        return located.record
