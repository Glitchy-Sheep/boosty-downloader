"""Resolve links to pages published later in a completed download run."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.application.post_pages import render_post_page
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.page_links import SavedPageLinkResolver

if TYPE_CHECKING:
    from boosty_downloader.application.download_context import DownloadContext
    from boosty_downloader.application.post_link_tracker import PostPageLocation
    from boosty_downloader.domain.stored_post import StoredPost


def repair_download_links(context: DownloadContext) -> None:
    """Refresh only affected sources; leave failure reporting to the run caller."""
    resolver = SavedPageLinkResolver(context.library_root, context.post_store.find_post)
    for source in context.page_links.ready_sources():
        written = _refresh_source(context, resolver, source)
        context.run_statistics.finish_pending_post(source.identity, written=written)
        if written:
            context.progress_reporter.notice(
                'Updated local post links: ' + source.folder
            )


def _refresh_source(
    context: DownloadContext,
    resolver: SavedPageLinkResolver,
    source: PostPageLocation,
) -> bool:
    record = _read_source(context, source)
    result = render_post_page(
        record,
        root=context.library_root,
        folder=source.folder,
        link_resolver=resolver,
    )
    if record.sync.page_template != PAGE_TEMPLATE_VERSION:
        record.sync.page_template = PAGE_TEMPLATE_VERSION
        context.post_store.save_post(source.folder, record)
    context.page_links.record_render(source, result.unresolved)
    return result.written


def _read_source(context: DownloadContext, source: PostPageLocation) -> StoredPost:
    identity = source.identity
    located = context.post_store.find_post(identity.author, identity.post_id)
    if located is None or located.record is None or located.folder != source.folder:
        message = f'Saved post changed location before resolving its links: {identity.post_id}'
        raise ValueError(message)
    record = located.record
    if record.post.author != identity.author or record.post.id != identity.post_id:
        message = 'Saved post identity changed before resolving its links'
        raise ValueError(message)
    return record
