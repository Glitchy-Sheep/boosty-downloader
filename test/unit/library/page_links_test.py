"""Static links require a complete canonical target and a usable saved page."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from errno import EACCES, ENOSYS, EPERM
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.domain.stored_post import PostMetadata, PostSync, StoredPost
from boosty_downloader.infrastructure.library.page_links import (
    SavedPageLinkResolver,
    is_linkable_page_folder,
)
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.application.ports import LinkResolver
    from boosty_downloader.domain.library import LocatedPost

_NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
_POST_ID = '12345678-first-full-id'


def _save(store: JsonPostRecords, post_id: str = _POST_ID) -> str:
    post = PostMetadata(
        post_id,
        'writer',
        f'https://boosty.to/writer/posts/{post_id}',
        'Сохранённый пост 100% #1',
        _NOW,
        _NOW,
    )
    folder = store.choose_post_folder(post)
    store.save_post(folder, StoredPost(post, PostSync(_NOW, _NOW)))
    return folder


def _link(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except NotImplementedError:
        pytest.skip('Filesystem does not support symlinks')
    except OSError as error:
        if (
            error.errno in {EPERM, EACCES, ENOSYS}
            or getattr(error, 'winerror', None) == 1314
        ):
            pytest.skip('Filesystem does not permit symlinks')
        raise


def test_lookup_observes_a_target_saved_later_with_the_shared_store(
    tmp_path: Path,
) -> None:
    store = JsonPostRecords(tmp_path)
    resolver: LinkResolver = SavedPageLinkResolver(tmp_path, store.find_post)
    assert resolver.post_folder('writer', _POST_ID) is None

    folder = _save(store)
    page = tmp_path / folder / 'post.html'
    assert resolver.post_folder('writer', _POST_ID) is None
    page.write_text('Saved page', encoding='utf-8')

    assert resolver.post_folder('writer', _POST_ID) == folder
    page.unlink()
    assert resolver.post_folder('writer', _POST_ID) is None


def test_full_ids_with_the_same_prefix_keep_separate_targets(tmp_path: Path) -> None:
    store = JsonPostRecords(tmp_path)
    first = _save(store)
    second_id = '12345678-second-full-id'
    second = _save(store, second_id)
    for folder in (first, second):
        (tmp_path / folder / 'post.html').write_text('Saved page', encoding='utf-8')
    resolver = SavedPageLinkResolver(tmp_path, store.find_post)

    assert first != second
    assert resolver.post_folder('writer', _POST_ID) == first
    assert resolver.post_folder('writer', second_id) == second
    assert resolver.post_folder('writer', '12345678') is None
    assert resolver.post_folder('other', _POST_ID) is None


@pytest.mark.parametrize(
    'target', ['recordless', 'corrupt', 'directory', 'page_link', 'folder_link']
)
def test_an_unusable_target_stays_remote(tmp_path: Path, target: str) -> None:
    store = JsonPostRecords(tmp_path)
    folder = _save(store)
    page = tmp_path / folder / 'post.html'
    page.write_text('Saved page', encoding='utf-8')
    record = page.with_name('post.json')
    match target:
        case 'recordless':
            record.unlink()
        case 'corrupt':
            record.write_text('{broken', encoding='utf-8')
        case 'directory':
            page.unlink()
            page.mkdir()
        case 'page_link':
            destination = tmp_path / 'unrelated.html'
            destination.write_text('Unrelated page', encoding='utf-8')
            page.unlink()
            _link(page, destination)
        case 'folder_link':
            destination = page.parent.with_name('moved')
            page.parent.rename(destination)
            _link(page.parent, destination, directory=True)

    resolver = SavedPageLinkResolver(tmp_path, store.find_post)
    assert resolver.post_folder('writer', _POST_ID) is None


def test_a_lookup_cannot_substitute_another_full_identity(tmp_path: Path) -> None:
    store = JsonPostRecords(tmp_path)
    folder = _save(store)
    (tmp_path / folder / 'post.html').write_text('Saved page', encoding='utf-8')
    located = store.find_post('writer', _POST_ID)

    def wrong_post(_author: str, _post_id: str) -> LocatedPost | None:
        return located

    resolver = SavedPageLinkResolver(tmp_path, wrong_post)
    assert resolver.post_folder('writer', 'other-full-id') is None
    assert resolver.post_folder('other', _POST_ID) is None


@pytest.mark.parametrize('existing', ['nothing', 'author', 'folder', 'page'])
def test_future_page_eligibility_never_creates_missing_paths(
    tmp_path: Path, existing: str
) -> None:
    root = tmp_path / 'library'
    folder = root / 'writer' / 'post'
    match existing:
        case 'author':
            folder.parent.mkdir(parents=True)
        case 'folder':
            folder.mkdir(parents=True)
        case 'page':
            folder.mkdir(parents=True)
            (folder / 'post.html').write_text('Saved page', encoding='utf-8')
    before = {path: path.stat().st_mtime_ns for path in tmp_path.rglob('*')}

    assert is_linkable_page_folder(root, 'writer/post', allow_missing=True)
    assert is_linkable_page_folder(root, 'writer/post') is (existing == 'page')
    assert {path: path.stat().st_mtime_ns for path in tmp_path.rglob('*')} == before


@pytest.mark.parametrize(
    'entry',
    ['author_file', 'author_link', 'folder_link', 'page_link', 'page_directory'],
)
def test_prospective_targets_reject_existing_redirects_and_special_paths(
    tmp_path: Path, entry: str
) -> None:
    root = tmp_path / 'library'
    folder = root / 'writer' / 'post'
    folder.mkdir(parents=True)
    match entry:
        case 'author_file':
            folder.rmdir()
            folder.parent.rmdir()
            folder.parent.write_text('Occupied', encoding='utf-8')
        case 'author_link':
            destination = root / 'other'
            folder.parent.rename(destination)
            _link(folder.parent, destination, directory=True)
        case 'folder_link':
            destination = root / 'writer' / 'other'
            folder.rename(destination)
            _link(folder, destination, directory=True)
        case 'page_link':
            destination = root / 'other.html'
            destination.write_text('Other', encoding='utf-8')
            _link(folder / 'post.html', destination)
        case 'page_directory':
            (folder / 'post.html').mkdir()

    assert not is_linkable_page_folder(root, 'writer/post', allow_missing=True)


@pytest.mark.skipif(not hasattr(os, 'mkfifo'), reason='Requires a filesystem FIFO')
def test_a_fifo_record_cannot_block_an_optional_link_lookup(tmp_path: Path) -> None:
    store = JsonPostRecords(tmp_path)
    folder = _save(store)
    page = tmp_path / folder / 'post.html'
    page.write_text('Saved page', encoding='utf-8')
    record_path = page.with_name('post.json')
    record_path.unlink()
    os.mkfifo(record_path)
    script = """
import sys
from pathlib import Path
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords
from boosty_downloader.infrastructure.library.page_links import SavedPageLinkResolver
root = Path(sys.argv[1])
store = JsonPostRecords(root)
try:
    store.find_post('writer', sys.argv[2])
except InvalidPostRecordError:
    pass
else:
    raise AssertionError('A selected FIFO record must be rejected')
resolver = SavedPageLinkResolver(root, store.find_post)
assert resolver.post_folder('writer', sys.argv[2]) is None
"""

    result = subprocess.run(  # noqa: S603 - fixed script and isolated fixture paths
        [sys.executable, '-c', script, str(tmp_path), _POST_ID],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert record_path.is_fifo()
    assert page.read_text(encoding='utf-8') == 'Saved page'
