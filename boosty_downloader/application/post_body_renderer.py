"""Render retained post content through the shared saved-page templates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.page_builder import build_post_page
from boosty_downloader.infrastructure.html_generator import render_html_body

if TYPE_CHECKING:
    from boosty_downloader.application.ports import MediaUrl
    from boosty_downloader.domain.stored_post import StoredPost


class StoredPostBodyRenderer:
    """Build an HTML body without a document wrapper or filesystem changes."""

    def render(self, record: StoredPost, *, media_url: MediaUrl) -> str:
        """Render current content and retained removed media at the supplied URLs."""
        return render_html_body(build_post_page(record, media_url=media_url))
