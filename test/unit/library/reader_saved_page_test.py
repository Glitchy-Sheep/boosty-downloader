"""Rendered-page ownership requires a canonical identity and an unclaimed path."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from boosty_downloader.domain.library import SavedPage
from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.stored_post import (
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.json_store import write_post_record
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
POST_ID = 'abcdefgh-first'


@dataclass(frozen=True)
class RenderedPost:
    root: Path
    folder: str
    record: StoredPost
    reader: JsonLibraryReader

    @property
    def page(self) -> str:
        return f'{self.folder}/post.html'

    @property
    def author_page(self) -> str:
        return self.page.removeprefix('writer/')


@pytest.fixture
def rendered(tmp_path: Path) -> RenderedPost:
    initialize_library(tmp_path)
    store = JsonPostStore(tmp_path)
    record = StoredPost(
        PostMetadata(POST_ID, 'writer', 'https://boosty.to/writer', 'Title', NOW, NOW),
        PostSync(NOW, NOW, page_template=1),
    )
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    reader = JsonLibraryReader(tmp_path)
    reader.prepare()
    return RenderedPost(tmp_path, folder, record, reader)


def test_proves_saved_page_from_canonical_record(rendered: RenderedPost) -> None:
    assert rendered.reader.saved_page('writer', rendered.author_page) == SavedPage(
        rendered.folder, rendered.page
    )


@pytest.mark.parametrize(
    'path',
    [
        'post.html',
        'unknown/post.html',
        'unknown/files/post.html',
        '../post.html',
        '/unknown/post.html',
        './unknown/post.html',
        'unknown//post.html',
    ],
)
def test_unknown_or_noncanonical_path_has_no_page_proof(
    rendered: RenderedPost, path: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        Path, 'read_bytes', Mock(side_effect=AssertionError('Read JSON'))
    )
    assert rendered.reader.saved_page('writer', path) is None
    assert rendered.reader.saved_page('other', rendered.author_page) is None


@pytest.mark.parametrize(
    'name', ['POST.HTML', 'post.html.', 'post.html ', 'post.html::$DATA']
)
def test_requested_alias_does_not_receive_page_proof(
    rendered: RenderedPost, name: str
) -> None:
    path = str(Path(rendered.author_page).with_name(name))
    assert rendered.reader.saved_page('writer', path) is None


def test_unrendered_record_has_no_page_proof(rendered: RenderedPost) -> None:
    rendered.record.sync.page_template = None
    write_post_record(rendered.root / rendered.folder, rendered.record)
    assert rendered.reader.saved_page('writer', rendered.author_page) is None


@pytest.mark.parametrize('field', ['path', 'preview_path'])
@pytest.mark.parametrize(
    'path', ['post.html', 'POST.HTML', 'post.html.', 'post.html ', 'post.html::$DATA']
)
def test_inventory_page_collision_has_no_page_proof(
    rendered: RenderedPost, field: str, path: str
) -> None:
    entry = MediaEntry(MediaKind.file, MediaStatus.pending, NOW, 0, removed_at=NOW)
    setattr(entry, field, path)
    rendered.record.media['file:page'] = entry
    write_post_record(rendered.root / rendered.folder, rendered.record)
    assert rendered.reader.saved_page('writer', rendered.author_page) is None


def test_same_attachment_name_in_subdirectory_does_not_claim_root_page(
    rendered: RenderedPost,
) -> None:
    rendered.record.media['file:page'] = MediaEntry(
        MediaKind.file,
        MediaStatus.pending,
        NOW,
        0,
        path='files/post.html',
        removed_at=NOW,
    )
    write_post_record(rendered.root / rendered.folder, rendered.record)
    assert rendered.reader.saved_page('writer', rendered.author_page) == SavedPage(
        rendered.folder, rendered.page
    )


def test_replaced_full_identity_has_no_page_proof(rendered: RenderedPost) -> None:
    replacement = replace(
        rendered.record, post=replace(rendered.record.post, id='abcdefgh-replaced')
    )
    write_post_record(rendered.root / rendered.folder, replacement)
    assert rendered.reader.saved_page('writer', rendered.author_page) is None


def test_missing_canonical_record_has_no_page_proof(rendered: RenderedPost) -> None:
    (rendered.root / rendered.folder / 'post.json').unlink()
    assert rendered.reader.saved_page('writer', rendered.author_page) is None


def test_corrupt_record_remains_a_read_failure(rendered: RenderedPost) -> None:
    (rendered.root / rendered.folder / 'post.json').write_bytes(b'{broken')
    with pytest.raises(LibraryReadError):
        rendered.reader.saved_page('writer', rendered.author_page)


def test_ambiguous_indexed_folder_has_no_page_proof(
    rendered: RenderedPost, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JsonPostStore(rendered.root)
    second = replace(
        rendered.record, post=replace(rendered.record.post, id='ijklmnop-second')
    )
    store.save_post(store.choose_post_folder(second.post), second)
    rendered.reader.prepare()
    index = LibraryIndex(rendered.root)
    with closing(sqlite3.connect(index.path)) as connection, connection:
        connection.execute('UPDATE posts SET folder=?', (rendered.folder,))
    monkeypatch.setattr(
        Path, 'read_bytes', Mock(side_effect=AssertionError('Read JSON'))
    )
    assert rendered.reader.saved_page('writer', rendered.author_page) is None


def test_page_folder_lookup_uses_author_folder_index(rendered: RenderedPost) -> None:
    with LibraryIndex(rendered.root).connect() as connection:
        plan = connection.execute(
            text(
                'EXPLAIN QUERY PLAN SELECT post_id FROM posts '
                'WHERE author = :author AND folder = :folder LIMIT 2'
            ),
            {'author': 'writer', 'folder': rendered.folder},
        ).all()
    assert any('ix_posts_author_folder' in str(row) for row in plan)
