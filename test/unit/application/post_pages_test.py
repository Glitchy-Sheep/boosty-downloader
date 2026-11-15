"""Page publication observes local links without owning canonical record updates."""

from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import quote

from boosty_downloader.application.post_pages import prepare_post_page, render_post_page
from boosty_downloader.domain.library import PostIdentity
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.post_folder import compose_post_directory_name
from boosty_downloader.domain.stored_post import (
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)

if TYPE_CHECKING:
    from pathlib import Path

_NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
_TARGET = PostIdentity('writer', 'target')
_HREF = 'https://boosty.to/writer/posts/target?mode=read#part'


@dataclass
class _Links:
    folders: dict[PostIdentity, str] = field(default_factory=dict[PostIdentity, str])
    lookups: list[PostIdentity] = field(default_factory=list[PostIdentity])

    def post_folder(self, author: str, post_id: str) -> str | None:
        identity = PostIdentity(author, post_id)
        self.lookups.append(identity)
        return self.folders.get(identity)


def _record() -> StoredPost:
    return StoredPost(
        PostMetadata(
            'source',
            'writer',
            'https://boosty.to/writer/posts/source',
            'Source',
            _NOW,
            _NOW,
        ),
        PostSync(_NOW, _NOW),
        [TextBlock([PostDataChunkText.TextFragment('Read next', link_url=_HREF)])],
    )


def _folder(record: StoredPost) -> str:
    post = record.post
    return f'{post.author}/{compose_post_directory_name(post.title, post.created_at, post.id)}'


def test_publish_tracks_unresolved_links_and_preserves_unchanged_page(
    tmp_path: Path,
) -> None:
    record = _record()
    before = deepcopy(record)
    folder = _folder(record)
    resolver = _Links()

    result = render_post_page(
        record, root=tmp_path, folder=folder, link_resolver=resolver
    )

    assert result.written
    assert result.unresolved == frozenset({_TARGET})
    page = tmp_path / folder / 'post.html'
    assert f'href="{_HREF}"' in page.read_text(encoding='utf-8')
    timestamp = 1_700_000_000_000_000_000
    os.utime(page, ns=(timestamp, timestamp))
    again = render_post_page(
        record, root=tmp_path, folder=folder, link_resolver=resolver
    )
    assert not again.written
    assert again.unresolved == result.unresolved
    assert page.stat().st_mtime_ns == timestamp
    assert record == before


def test_new_target_rewrites_only_the_authored_link_and_does_not_mark_record(
    tmp_path: Path,
) -> None:
    record = _record()
    before = deepcopy(record)
    folder = _folder(record)
    resolver = _Links()
    render_post_page(record, root=tmp_path, folder=folder, link_resolver=resolver)
    resolver.folders[_TARGET] = 'writer/Сохранено 100% #1'

    result = render_post_page(
        record, root=tmp_path, folder=folder, link_resolver=resolver
    )

    assert result.written
    assert result.unresolved == frozenset()
    page = (tmp_path / folder / 'post.html').read_text(encoding='utf-8')
    relative = quote('../Сохранено 100% #1/post.html', safe='/')
    assert f'href="{relative}?mode=read#part"' in page
    assert record == before


def test_prepared_page_matches_published_bytes_without_mutating_record(
    tmp_path: Path,
) -> None:
    record = _record()
    before = deepcopy(record)
    folder = _folder(record)
    resolver = _Links({_TARGET: 'writer/Сохранено 100% #1'})

    prepared = prepare_post_page(record, folder=folder, link_resolver=resolver)

    assert list(tmp_path.iterdir()) == []
    assert record == before
    assert prepared.unresolved == frozenset()
    result = render_post_page(
        record, root=tmp_path, folder=folder, link_resolver=resolver
    )
    assert result.unresolved == prepared.unresolved
    assert (tmp_path / folder / 'post.html').read_bytes() == prepared.content


def test_publication_projects_each_authored_link_only_once(tmp_path: Path) -> None:
    record = _record()
    resolver = _Links()

    result = render_post_page(
        record, root=tmp_path, folder=_folder(record), link_resolver=resolver
    )

    assert resolver.lookups == [_TARGET]
    assert result.unresolved == frozenset({_TARGET})


def test_prepared_page_keeps_missing_target_and_uses_folder_as_empty_title() -> None:
    record = _record()
    record.post.title = '  '

    prepared = prepare_post_page(
        record, folder='writer/Folder title', link_resolver=_Links()
    )

    assert prepared.unresolved == frozenset({_TARGET})
    assert f'href="{_HREF}"'.encode() in prepared.content
    assert b'<title>Folder title</title>' in prepared.content
