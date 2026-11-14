"""Stored opener locations use exact identities without inspecting local files."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from sqlalchemy import event, select, update

from boosty_downloader.domain.library import LibraryPost, PostAccess, PostOverview
from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.library_media import MediaIdentity
from boosty_downloader.domain.stored_post import (
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library import _reader_paths as path_queries
from boosty_downloader.infrastructure.library._index_engine import make_index_engine
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.index_projection import project_post
from boosty_downloader.infrastructure.library.index_sources import PostSource
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

if TYPE_CHECKING:
    from os import stat_result

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
MEDIA_ID = 'file:shared?full=id#with:separators'
MEDIA_PATH = 'files/песня 100% #, запись.mp3'


@dataclass(frozen=True, slots=True)
class _Library:
    root: Path
    index: LibraryIndex
    reader: JsonLibraryReader


@pytest.fixture
def library(tmp_path: Path) -> _Library:
    root = tmp_path / 'library'
    initialize_library(root)
    index = LibraryIndex(root)
    index.ensure()
    return _Library(root, index, JsonLibraryReader(root))


def _record(post_id: str = 'post', author: str = 'writer') -> StoredPost:
    record = StoredPost(
        PostMetadata(
            post_id,
            author,
            f'https://boosty.to/{author}/posts/{post_id}',
            post_id,
            NOW,
            NOW,
        ),
        PostSync(NOW, NOW),
    )
    record.media[MEDIA_ID] = MediaEntry(
        MediaKind.file,
        MediaStatus.downloaded,
        NOW,
        0,
        path=MEDIA_PATH,
        size=12,
    )
    return record


def _write(
    index: LibraryIndex, record: StoredPost, access: PostAccess = PostAccess.open
) -> str:
    folder = f'{record.post.author}/{record.post.id}'
    source = PostSource(LibraryPost(PostOverview(record.post, access), record, folder))
    index.upsert_post(project_post(source))
    return folder


@pytest.mark.parametrize('kind', list(MediaKind))
@pytest.mark.parametrize('access', list(PostAccess))
@pytest.mark.parametrize('removed', [False, True])
def test_recorded_media_and_post_paths_keep_retained_downloads(
    library: _Library, kind: MediaKind, access: PostAccess, *, removed: bool
) -> None:
    record = _record()
    entry = record.media[MEDIA_ID]
    entry.kind = kind
    entry.removed_at = NOW if removed else None
    folder = _write(library.index, record, access)

    assert not (library.root / folder).exists()
    assert library.reader.post_folder('writer', 'post') == folder
    assert library.reader.media_path('writer', MediaIdentity('post', MEDIA_ID)) == (
        f'{folder}/{MEDIA_PATH}'
    )


def test_locations_use_full_author_post_and_media_identity(library: _Library) -> None:
    for author in ('writer', 'writer-similar'):
        for post_id in ('sameprefix-one', 'sameprefix-two'):
            record = _record(post_id, author)
            _write(library.index, record)
            assert library.reader.post_folder(author, post_id) == f'{author}/{post_id}'
            assert library.reader.media_path(
                author, MediaIdentity(post_id, MEDIA_ID)
            ) == (f'{author}/{post_id}/{MEDIA_PATH}')
    assert library.reader.post_folder('writer', 'sameprefix') is None
    assert (
        library.reader.media_path('writer', MediaIdentity('sameprefix', MEDIA_ID))
        is None
    )
    assert (
        library.reader.media_path(
            'writer', MediaIdentity('sameprefix-one', MEDIA_ID.partition('?')[0])
        )
        is None
    )
    assert (
        library.reader.media_path('absent', MediaIdentity('sameprefix-one', MEDIA_ID))
        is None
    )


@pytest.mark.parametrize('status', list(MediaStatus))
def test_only_downloaded_media_has_an_openable_recorded_path(
    library: _Library, status: MediaStatus
) -> None:
    record = _record()
    record.media[MEDIA_ID].status = status
    folder = _write(library.index, record)

    expected = f'{folder}/{MEDIA_PATH}' if status is MediaStatus.downloaded else None
    assert (
        library.reader.media_path('writer', MediaIdentity('post', MEDIA_ID)) == expected
    )
    assert library.reader.post_folder('writer', 'post') == folder


def test_unknown_and_locked_only_posts_have_no_recorded_folder(
    library: _Library,
) -> None:
    record = _record('locked')
    source = PostSource(LibraryPost(PostOverview(record.post, PostAccess.locked)))
    library.index.upsert_post(project_post(source))

    assert library.reader.post_folder('writer', 'locked') is None
    assert library.reader.post_folder('writer', 'unknown') is None
    assert library.reader.post_folder('unknown', 'locked') is None
    assert (
        library.reader.media_path('writer', MediaIdentity('locked', MEDIA_ID)) is None
    )


def _change_media(library: _Library, **values: object) -> None:
    engine = make_index_engine(library.index.path, writable=True)
    try:
        with engine.begin() as connection:
            connection.execute(update(IndexMedia).values(**values))
    finally:
        engine.dispose()


def _change_folder(library: _Library, folder: object) -> None:
    engine = make_index_engine(library.index.path, writable=True)
    try:
        with engine.begin() as connection:
            connection.execute(update(IndexPost).values(folder=folder))
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    'path',
    [
        None,
        '',
        b'writer/post/file',
        '/writer/post/file',
        'other/post/file',
        'writer/post-copy/file',
        'writer/post',
        'writer/post/../other/file',
        'writer/post//file',
        'writer/post/./file',
        'writer/post/C:/file',
        'writer/post/C:file',
        'writer/post/file\\name',
        'writer/post/file\0name',
    ],
)
def test_corrupt_media_path_is_a_private_read_error(
    library: _Library, path: object
) -> None:
    _write(library.index, _record())
    _change_media(library, path=path)

    with pytest.raises(LibraryReadError, match='could not be read') as error:
        library.reader.media_path('writer', MediaIdentity('post', MEDIA_ID))
    assert str(library.root) not in str(error.value)
    assert str(error.value) == 'The library data could not be read'


@pytest.mark.parametrize('size', [None, -1, 1.5, float('inf'), 'not-a-size'])
def test_inconsistent_downloaded_size_is_a_read_error(
    library: _Library, size: object
) -> None:
    _write(library.index, _record())
    _change_media(library, size=size)

    with pytest.raises(LibraryReadError):
        library.reader.media_path('writer', MediaIdentity('post', MEDIA_ID))


def test_zero_byte_download_has_a_recorded_path(library: _Library) -> None:
    record = _record()
    record.media[MEDIA_ID].size = 0
    folder = _write(library.index, record)

    assert library.reader.media_path('writer', MediaIdentity('post', MEDIA_ID)) == (
        f'{folder}/{MEDIA_PATH}'
    )


@pytest.mark.parametrize(
    'folder',
    [
        '',
        b'writer/post',
        'writer',
        'other/post',
        '/writer/post',
        'writer/../post',
        'writer//post',
        'C:/post',
        'writer/C:/post',
        'writer/C:post',
    ],
)
def test_corrupt_post_folder_is_a_read_error_for_both_lookups(
    library: _Library, folder: object
) -> None:
    _write(library.index, _record())
    _change_folder(library, folder)

    with pytest.raises(LibraryReadError):
        library.reader.post_folder('writer', 'post')
    with pytest.raises(LibraryReadError):
        library.reader.media_path('writer', MediaIdentity('post', MEDIA_ID))


def test_downloaded_media_requires_a_post_folder(library: _Library) -> None:
    _write(library.index, _record())
    _change_folder(library, None)

    with pytest.raises(LibraryReadError):
        library.reader.media_path('writer', MediaIdentity('post', MEDIA_ID))


@pytest.mark.parametrize('other_author', ['writer', 'other'])
def test_media_cannot_refer_to_a_different_owning_post(
    library: _Library, other_author: str
) -> None:
    _write(library.index, _record())
    _write(library.index, _record('other-post', other_author))
    engine = make_index_engine(library.index.path, writable=True)
    try:
        with engine.begin() as connection:
            other = connection.execute(
                select(IndexPost.id).where(IndexPost.post_id == 'other-post')
            ).scalar_one()
            connection.execute(
                update(IndexMedia)
                .where(IndexMedia.post_id == 'post')
                .values(post_row_id=other)
            )
    finally:
        engine.dispose()

    with pytest.raises(LibraryReadError):
        library.reader.media_path('writer', MediaIdentity('post', MEDIA_ID))


def test_locations_require_a_prepared_index(tmp_path: Path) -> None:
    reader = JsonLibraryReader(tmp_path / 'missing')

    with pytest.raises(LibraryReadError):
        reader.post_folder('writer', 'post')
    with pytest.raises(LibraryReadError):
        reader.media_path('writer', MediaIdentity('post', MEDIA_ID))
    assert not (tmp_path / 'missing').exists()


@pytest.mark.parametrize('post_count', [1, 25])
def test_recorded_path_queries_use_one_select_each(
    library: _Library, post_count: int
) -> None:
    for number in range(post_count):
        _write(library.index, _record(str(number)))
    with library.index.connect() as connection:
        trace = Mock()
        event.listen(connection, 'before_cursor_execute', trace)
        assert path_queries.read_post_folder(connection, 'writer', '0') == 'writer/0'
        assert (
            path_queries.read_media_path(
                connection, 'writer', MediaIdentity('0', MEDIA_ID)
            )
            == f'writer/0/{MEDIA_PATH}'
        )
    assert trace.call_count == 2


def test_locations_do_not_read_records_or_inspect_media(
    library: _Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(library.index, _record())
    read_bytes = Path.read_bytes
    stat = Path.stat

    def guard_read(path: Path) -> bytes:
        assert path.name not in {
            'post.json',
            'viewer.json',
            'author.json',
            'locked.json',
        }
        return read_bytes(path)

    def guard_stat(path: Path, *, follow_symlinks: bool = True) -> stat_result:
        assert not path.is_relative_to(library.root / 'writer')
        return stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, 'read_bytes', guard_read)
    monkeypatch.setattr(Path, 'stat', guard_stat)
    monkeypatch.setattr(
        Path, 'iterdir', Mock(side_effect=AssertionError('Directory walk'))
    )
    assert library.reader.post_folder('writer', 'post') == 'writer/post'
    assert library.reader.media_path('writer', MediaIdentity('post', MEDIA_ID)) == (
        f'writer/post/{MEDIA_PATH}'
    )
