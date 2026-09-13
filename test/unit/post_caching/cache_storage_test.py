"""SQLiteCacheStorage removes the cache file and nothing else of the user's."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.loggers.base import RichLogger
from boosty_downloader.infrastructure.post_caching.post_cache import SQLitePostCache
from boosty_downloader.infrastructure.post_caching.storage import SQLiteCacheStorage

if TYPE_CHECKING:
    from pathlib import Path


def _create_cache(destination: Path) -> None:
    with SQLitePostCache(destination=destination, logger=RichLogger('storage-test')):
        pass


def test_exists_follows_the_database_file(tmp_path: Path):
    storage = SQLiteCacheStorage(tmp_path / 'author')
    assert not storage.exists()
    _create_cache(tmp_path / 'author')
    assert storage.exists()


def test_remove_drops_an_empty_cache_folder(tmp_path: Path):
    """A folder that held only the cache must not linger as an empty leftover."""
    _create_cache(tmp_path / 'author')
    SQLiteCacheStorage(tmp_path / 'author').remove()
    assert not (tmp_path / 'author').exists()


def test_remove_keeps_a_folder_with_downloads(tmp_path: Path):
    """The cache lives next to the posts by default: they must survive a clean."""
    _create_cache(tmp_path / 'author')
    post = tmp_path / 'author' / '2026-01-01 - post (00000000)' / 'post.html'
    post.parent.mkdir()
    post.write_text('<html></html>', encoding='utf-8')

    storage = SQLiteCacheStorage(tmp_path / 'author')
    storage.remove()

    assert not storage.exists()
    assert post.exists()


def test_remove_on_a_missing_cache_is_a_no_op(tmp_path: Path):
    SQLiteCacheStorage(tmp_path / 'author').remove()
    assert not (tmp_path / 'author').exists()
