"""Publish complete saved pages with current local post-link destinations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from boosty_downloader.application.page_builder import build_post_page
from boosty_downloader.application.post_links import SavedPostLinks
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html,
    write_html_page,
)
from boosty_downloader.infrastructure.media_output_paths import (
    resolve_media_destination,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import LinkResolver
    from boosty_downloader.domain.library import PostIdentity
    from boosty_downloader.domain.stored_post import StoredPost


@dataclass(frozen=True, slots=True)
class PreparedPostPage:
    """Complete HTML and unresolved references, ready for comparison or publication."""

    content: bytes
    unresolved: frozenset[PostIdentity]


@dataclass(frozen=True, slots=True)
class PageRenderResult:
    """Publication outcome; canonical template markers remain the caller's work."""

    written: bool
    unresolved: frozenset[PostIdentity]


def prepare_post_page(
    record: StoredPost, *, folder: str, link_resolver: LinkResolver
) -> PreparedPostPage:
    """Project complete HTML without changing the record or publishing files."""
    links = SavedPostLinks(link_resolver, folder)
    html = render_html(
        build_post_page(record, link_url=links),
        page_title=record.post.title.strip() or PurePosixPath(folder).name,
    )
    return PreparedPostPage(html.encode('utf-8'), links.unresolved)


def render_post_page(
    record: StoredPost, *, root: Path, folder: str, link_resolver: LinkResolver
) -> PageRenderResult:
    """Publish a record in its owned folder, preserving identical page bytes."""
    destination = resolve_media_destination(root, folder, 'post.html')
    prepared = prepare_post_page(record, folder=folder, link_resolver=link_resolver)
    written = write_html_page(destination, prepared.content, only_if_changed=True)
    return PageRenderResult(written, prepared.unresolved)
