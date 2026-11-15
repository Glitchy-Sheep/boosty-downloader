"""Offline rendering observes local files and preserves canonical ownership."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from errno import EACCES, ENOSYS, EPERM
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.application.use_cases.render_posts import (
    RenderPostsUseCase,
    RenderReport,
)
from boosty_downloader.domain.library import SavedPost
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.post_folder import compose_post_directory_name
from boosty_downloader.domain.stored_post import (
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION

if TYPE_CHECKING:
    from collections.abc import Iterator

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
REMOVED_AT = NOW + timedelta(days=1)
POST_ID = 'abcdefgh-saved'
FILE_ID = 'file:material'
FILE_PATH = 'files/material.zip'


class _MemoryCollection:
    def __init__(self, *posts: SavedPost) -> None:
        self.posts = list(posts)
        self.saved: list[SavedPost] = []
        self.selected_authors: list[str | None] = []

    def iter_saved_posts(self, author: str | None = None) -> Iterator[SavedPost]:
        self.selected_authors.append(author)
        for saved in self.posts:
            if author is None or saved.record.post.author == author:
                yield saved

    def save_post(self, folder: str, record: StoredPost) -> None:
        self.saved.append(SavedPost(folder, deepcopy(record)))


def _post(
    root: Path, *, author: str = 'writer', title: str = 'Stored lesson'
) -> SavedPost:
    record = StoredPost(
        PostMetadata(
            POST_ID,
            author,
            f'https://boosty.to/{author}/posts/{POST_ID}',
            title,
            NOW,
            NOW,
            tags=['lesson'],
        ),
        PostSync(NOW, NOW),
        [TextBlock([PostDataChunkText.TextFragment('Saved body text')])],
    )
    folder = f'{author}/{compose_post_directory_name(title, NOW, POST_ID)}'
    (root / folder).mkdir(parents=True)
    return SavedPost(folder, record)


def _add_file(
    saved: SavedPost,
    *,
    status: MediaStatus = MediaStatus.downloaded,
    removed: bool = False,
    path: str = FILE_PATH,
) -> None:
    saved.record.media[FILE_ID] = MediaEntry(
        kind=MediaKind.file,
        status=status,
        added_at=NOW,
        position=0,
        path=path,
        size=100,
        filename='material.zip',
        removed_at=REMOVED_AT if removed else None,
    )
    if not removed:
        saved.record.blocks.append(MediaBlock(FILE_ID))


def _write_media(
    root: Path, saved: SavedPost, data: bytes, path: str = FILE_PATH
) -> Path:
    target = root / saved.folder / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _page(root: Path, saved: SavedPost) -> str:
    return (root / saved.folder / 'post.html').read_text(encoding='utf-8')


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
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


@pytest.mark.parametrize('author', [None, 'writer', 'other', 'absent'])
def test_renders_only_selected_authors_and_reports_completed_pages(
    tmp_path: Path, author: str | None
) -> None:
    first = _post(tmp_path)
    second = _post(tmp_path, author='other')
    store = _MemoryCollection(first, second)

    report = RenderPostsUseCase(tmp_path, store).execute(author)

    selected = [
        saved
        for saved in store.posts
        if author is None or saved.record.post.author == author
    ]
    assert report == RenderReport(pages=len(selected))
    assert store.selected_authors == [author]
    assert store.saved == [
        SavedPost(
            saved.folder,
            replace(
                saved.record,
                sync=replace(saved.record.sync, page_template=PAGE_TEMPLATE_VERSION),
            ),
        )
        for saved in selected
    ]
    for saved in store.posts:
        assert (tmp_path / saved.folder / 'post.html').exists() == (saved in selected)


def test_missing_recorded_file_becomes_a_deleted_placeholder_without_mutating_input(
    tmp_path: Path,
) -> None:
    saved = _post(tmp_path)
    _add_file(saved)
    original = deepcopy(saved)
    store = _MemoryCollection(saved)

    assert RenderPostsUseCase(tmp_path, store).execute() == RenderReport(pages=1)

    current = store.saved[0].record
    entry = current.media[FILE_ID]
    assert entry.status is MediaStatus.deleted
    assert entry.path == FILE_PATH
    assert entry.size == 100
    assert entry.added_at == NOW
    assert current.sync.synced_at == NOW
    assert current.sync.first_downloaded_at == NOW
    assert current.sync.page_template == PAGE_TEMPLATE_VERSION
    assert 'File deleted from disk' in _page(tmp_path, saved)
    assert 'href="files/material.zip"' not in _page(tmp_path, saved)
    assert saved == original
    assert not (tmp_path / saved.folder / FILE_PATH).exists()


@pytest.mark.parametrize('data', [b'returned local bytes', b''])
def test_returned_recorded_file_uses_actual_size_without_changing_its_bytes(
    tmp_path: Path, data: bytes
) -> None:
    saved = _post(tmp_path)
    _add_file(saved, status=MediaStatus.deleted)
    media = _write_media(tmp_path, saved, data)
    modified = media.stat().st_mtime_ns
    store = _MemoryCollection(saved)

    RenderPostsUseCase(tmp_path, store).execute()

    entry = store.saved[0].record.media[FILE_ID]
    assert entry.status is MediaStatus.downloaded
    assert entry.path == FILE_PATH
    assert entry.size == len(data)
    assert entry.added_at == NOW
    assert 'href="files/material.zip"' in _page(tmp_path, saved)
    assert 'File deleted from disk' not in _page(tmp_path, saved)
    assert media.read_bytes() == data
    assert media.stat().st_mtime_ns == modified


@pytest.mark.parametrize('present', [False, True])
def test_removed_media_keeps_its_history_and_appears_only_while_on_disk(
    tmp_path: Path, *, present: bool
) -> None:
    saved = _post(tmp_path)
    _add_file(saved, removed=True)
    if present:
        _write_media(tmp_path, saved, b'retained')
    store = _MemoryCollection(saved)

    RenderPostsUseCase(tmp_path, store).execute()

    entry = store.saved[0].record.media[FILE_ID]
    assert entry.removed_at == REMOVED_AT
    assert entry.added_at == NOW
    expected_status = MediaStatus.downloaded if present else MediaStatus.deleted
    assert entry.status is expected_status
    assert ('Removed by the author' in _page(tmp_path, saved)) is present
    assert ('href="files/material.zip"' in _page(tmp_path, saved)) is present


@pytest.mark.parametrize(
    'status', [MediaStatus.pending, MediaStatus.failed, MediaStatus.unavailable]
)
def test_offline_render_does_not_adopt_unconfirmed_files(
    tmp_path: Path, status: MediaStatus
) -> None:
    saved = _post(tmp_path)
    _add_file(saved, status=status)
    _write_media(tmp_path, saved, b'possibly partial')
    store = _MemoryCollection(saved)

    RenderPostsUseCase(tmp_path, store).execute()

    assert store.saved[0].record.media[FILE_ID].status is status
    assert 'href="files/material.zip"' not in _page(tmp_path, saved)


def test_unchanged_record_is_not_saved_but_page_is_always_rebuilt(
    tmp_path: Path,
) -> None:
    saved = _post(tmp_path)
    saved.record.sync.page_template = PAGE_TEMPLATE_VERSION
    page = tmp_path / saved.folder / 'post.html'
    page.write_text('Old page', encoding='utf-8')
    store = _MemoryCollection(saved)

    assert RenderPostsUseCase(tmp_path, store).execute() == RenderReport(pages=1)

    assert 'Saved body text' in _page(tmp_path, saved)
    assert 'Old page' not in _page(tmp_path, saved)
    assert store.saved == []


def test_failed_page_write_does_not_save_observations_or_template_marker(
    tmp_path: Path,
) -> None:
    saved = _post(tmp_path)
    _add_file(saved)
    original = deepcopy(saved)
    page = tmp_path / saved.folder / 'post.html'
    page.mkdir()
    store = _MemoryCollection(saved)

    with pytest.raises(OSError, match=r'post\.html'):
        RenderPostsUseCase(tmp_path, store).execute()

    assert page.is_dir()
    assert store.saved == []
    assert saved == original


def test_record_save_sees_completed_html_and_its_failure_propagates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = _post(tmp_path)
    store = _MemoryCollection(saved)

    def fail_save(folder: str, record: StoredPost) -> None:
        assert folder == saved.folder
        assert record.sync.page_template == PAGE_TEMPLATE_VERSION
        assert 'Saved body text' in _page(tmp_path, saved)
        message = 'Record storage failed'
        raise OSError(message)

    monkeypatch.setattr(store, 'save_post', fail_save)
    with pytest.raises(OSError, match='Record storage failed'):
        RenderPostsUseCase(tmp_path, store).execute()
    assert saved.record.sync.page_template is None


def test_blank_title_uses_existing_folder_name(tmp_path: Path) -> None:
    saved = _post(tmp_path)
    saved.record.post.title = '  '
    store = _MemoryCollection(saved)

    RenderPostsUseCase(tmp_path, store).execute()

    assert f'<title>{Path(saved.folder).name}</title>' in _page(tmp_path, saved)


def test_ancillary_records_and_index_are_not_read_or_changed(tmp_path: Path) -> None:
    saved = _post(tmp_path)
    store = _MemoryCollection(saved)
    unrelated = [
        tmp_path / saved.folder / 'viewer.json',
        tmp_path / 'writer' / '.boosty-downloader' / 'author.json',
        tmp_path / 'writer' / '.boosty-downloader' / 'locked.json',
        tmp_path / '.boosty-downloader' / 'index.db',
    ]
    for path in unrelated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'invalid ancillary data')
    modified = {path: path.stat().st_mtime_ns for path in unrelated}

    RenderPostsUseCase(tmp_path, store).execute()

    assert 'Saved body text' in _page(tmp_path, saved)
    for path in unrelated:
        assert path.read_bytes() == b'invalid ancillary data'
        assert path.stat().st_mtime_ns == modified[path]


def test_recorded_case_alias_is_confirmed_by_the_filesystem(tmp_path: Path) -> None:
    saved = _post(tmp_path)
    recorded = 'files/MATERIAL.zip'
    _add_file(saved, status=MediaStatus.deleted, path=recorded)
    media = _write_media(tmp_path, saved, b'local material')
    recorded_exists = (tmp_path / saved.folder / recorded).exists()
    store = _MemoryCollection(saved)

    RenderPostsUseCase(tmp_path, store).execute()

    entry = store.saved[0].record.media[FILE_ID]
    if recorded_exists:
        assert entry.status is MediaStatus.downloaded
        assert entry.path == FILE_PATH
        assert entry.size == media.stat().st_size
    else:
        assert entry.status is MediaStatus.deleted
        assert entry.path == recorded
    assert media.read_bytes() == b'local material'


def test_escaping_post_folder_cannot_create_a_page(tmp_path: Path) -> None:
    root = tmp_path / 'library'
    outside = tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    saved = _post(root)
    escaping = SavedPost('../outside', saved.record)
    store = _MemoryCollection(escaping)

    with pytest.raises(ValueError, match='portable relative file path'):
        RenderPostsUseCase(root, store).execute()

    assert not (outside / 'post.html').exists()
    assert store.saved == []


def test_page_symlink_does_not_overwrite_its_external_target(tmp_path: Path) -> None:
    root = tmp_path / 'library'
    saved = _post(root)
    outside = tmp_path / 'outside.html'
    outside.write_text('Keep external content', encoding='utf-8')
    page = root / saved.folder / 'post.html'
    _symlink(page, outside)
    store = _MemoryCollection(saved)

    with pytest.raises(ValueError, match='destination is a link'):
        RenderPostsUseCase(root, store).execute()

    assert page.is_symlink()
    assert outside.read_text(encoding='utf-8') == 'Keep external content'
    assert store.saved == []
