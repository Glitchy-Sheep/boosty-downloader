"""Rebuild saved post pages from canonical content and current local files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from boosty_downloader.application.page_builder import build_post_page
from boosty_downloader.application.reconcile import observe_recorded_files
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.html_generator.renderer import render_html_to_file
from boosty_downloader.infrastructure.library.media_snapshot import read_media_snapshot
from boosty_downloader.infrastructure.media_output_paths import (
    resolve_media_destination,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import StoredPostCollection
    from boosty_downloader.domain.library import SavedPost
    from boosty_downloader.domain.stored_post import StoredPost


@dataclass(frozen=True, slots=True)
class RenderReport:
    """Pages successfully rebuilt from saved records."""

    pages: int


class RenderPostsUseCase:
    """Render saved bodies without network, index or viewing-state dependencies."""

    def __init__(self, library_root: Path, store: StoredPostCollection) -> None:
        self._root = library_root
        self._store = store

    def execute(self, author: str | None = None) -> RenderReport:
        """Rebuild each selected saved page; propagate failures without a success report."""
        pages = 0
        for saved in self._store.iter_saved_posts(author):
            self._render_post(saved)
            pages += 1
        return RenderReport(pages=pages)

    def _render_post(self, saved: SavedPost) -> None:
        record = _observe_local_media(self._root, saved)
        destination = resolve_media_destination(self._root, saved.folder, 'post.html')
        render_html_to_file(
            build_post_page(record),
            out_path=destination,
            page_title=record.post.title.strip() or PurePosixPath(saved.folder).name,
        )
        record.sync.page_template = PAGE_TEMPLATE_VERSION
        if record != saved.record:
            self._store.save_post(saved.folder, record)


def _observe_local_media(root: Path, saved: SavedPost) -> StoredPost:
    paths = [
        entry.path for entry in saved.record.media.values() if entry.path is not None
    ]
    disk = read_media_snapshot(root, saved.folder, queried_paths=paths)
    return observe_recorded_files(saved.record, disk)
