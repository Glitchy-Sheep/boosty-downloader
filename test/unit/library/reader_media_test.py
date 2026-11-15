"""Media lists use indexed retained files, individual marks and one read snapshot."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from sqlalchemy import event, update

from boosty_downloader.domain.library import (
    LibraryPost,
    MediaCounts,
    PostAccess,
    PostOrder,
    PostOverview,
)
from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.library_media import (
    LibraryMediaPage,
    LibraryMediaPost,
    LibraryMediaView,
    MediaFilters,
)
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library import _reader_media as media_queries
from boosty_downloader.infrastructure.library import reader as reader_module
from boosty_downloader.infrastructure.library._index_engine import make_index_engine
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.index_projection import (
    project_author,
    project_post,
)
from boosty_downloader.infrastructure.library.index_sources import (
    AuthorSource,
    PostSource,
)
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

if TYPE_CHECKING:
    from os import stat_result

    from sqlalchemy import Connection

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(days=1)
LATER = NOW + timedelta(days=1)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    root = tmp_path / 'library'
    initialize_library(root)
    return root


@pytest.fixture
def index(root: Path) -> LibraryIndex:
    index = LibraryIndex(root)
    index.ensure()
    return index


@pytest.fixture
def reader(root: Path, index: LibraryIndex) -> JsonLibraryReader:  # noqa: ARG001 - prepare index
    return JsonLibraryReader(root)


def _record(post_id: str = 'post', author: str = 'writer') -> StoredPost:
    return StoredPost(
        PostMetadata(
            post_id,
            author,
            f'https://boosty.to/{author}/posts/{post_id}',
            f'Title {post_id}',
            NOW,
            NOW,
        ),
        PostSync(NOW, NOW),
    )


def _write(
    index: LibraryIndex,
    record: StoredPost,
    *,
    marks: PostMarks | None = None,
    access: PostAccess = PostAccess.open,
) -> None:
    source = PostSource(
        LibraryPost(
            PostOverview(record.post, access),
            record,
            f'{record.post.author}/{record.post.id}',
        ),
        marks=marks or PostMarks(),
        cover_path=f'{record.post.author}/{record.post.id}/cover.jpg',
    )
    index.upsert_post(project_post(source))


def _media(kind: MediaKind = MediaKind.image, position: int = 0) -> MediaEntry:
    return MediaEntry(
        kind,
        MediaStatus.downloaded,
        NOW,
        position,
        path=f'media/{kind.value}-{position}.bin',
        size=23,
    )


@pytest.fixture
def inventory(index: LibraryIndex) -> StoredPost:
    record = _record()
    for kind in MediaKind:
        for status in MediaStatus:
            for removed in (False, True):
                identity = f'{kind.value}:{status.value}:{removed}'
                record.media[identity] = replace(
                    _media(kind, len(record.media)),
                    status=status,
                    removed_at=LATER if removed else None,
                )
    _write(index, record)
    return record


@pytest.mark.parametrize(
    ('view', 'kinds', 'missing'),
    [
        (
            LibraryMediaView.all,
            {
                MediaKind.image,
                MediaKind.boosty_video,
                MediaKind.external_video,
                MediaKind.audio,
            },
            16,
        ),
        (LibraryMediaView.image, {MediaKind.image}, 4),
        (LibraryMediaView.video, {MediaKind.boosty_video, MediaKind.external_video}, 8),
        (LibraryMediaView.audio, {MediaKind.audio}, 4),
        (LibraryMediaView.file, {MediaKind.file}, 4),
    ],
)
def test_views_include_retained_downloads_and_count_only_current_missing(
    reader: JsonLibraryReader,
    inventory: StoredPost,
    view: LibraryMediaView,
    kinds: set[MediaKind],
    missing: int,
) -> None:
    page = reader.list_media('writer', view, MediaFilters())

    assert {item.media_id for item in page.items} == {
        identity
        for identity, entry in inventory.media.items()
        if entry.kind in kinds and entry.status is MediaStatus.downloaded
    }
    assert page.counts == MediaCounts(images=2, videos=4, files=2, audio=2)
    assert page.missing == missing
    assert list(page.posts) == ['post']
    assert page.posts['post'] == LibraryMediaPost(
        'Title post', 'writer/post/cover.jpg', None, favorite=False
    )
    assert [item.entry.removed_at is not None for item in page.items] == [False] * len(
        kinds
    ) + [True] * len(kinds)


@pytest.mark.parametrize('order', list(PostOrder))
def test_order_uses_full_post_ids_then_inventory_position_and_keeps_removed_last(
    index: LibraryIndex, reader: JsonLibraryReader, order: PostOrder
) -> None:
    for post_id, created in [
        ('sameprefix-a', NOW),
        ('sameprefix-b', NOW),
        ('earlier', EARLIER),
    ]:
        record = _record(post_id)
        record.post.created_at = created
        record.media = {
            'image:z': _media(position=2),
            'image:b': _media(position=1),
            'image:a': _media(position=1),
            'image:removed': replace(_media(position=3), removed_at=LATER),
        }
        _write(index, record)
    engine = make_index_engine(index.path, writable=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                update(IndexMedia)
                .where(IndexMedia.media_id.in_(['image:a', 'image:b']))
                .values(position=1)
            )
            connection.execute(
                update(IndexMedia)
                .where(IndexMedia.media_id == 'image:z')
                .values(position=2)
            )
    finally:
        engine.dispose()

    page = reader.list_media(
        'writer', LibraryMediaView.image, MediaFilters(order=order)
    )
    post_ids = ['earlier', 'sameprefix-a', 'sameprefix-b']
    if order is PostOrder.newest:
        post_ids.reverse()
    expected = [
        (post_id, media_id)
        for post_id in post_ids
        for media_id in ('image:a', 'image:b', 'image:z')
    ]
    expected.extend((post_id, 'image:removed') for post_id in post_ids)
    assert [(item.post_id, item.media_id) for item in page.items] == expected
    assert set(page.posts) == set(post_ids)


@pytest.mark.parametrize('unseen', [False, True])
@pytest.mark.parametrize('favorites', [False, True])
def test_filters_use_individual_added_and_finished_marks_even_for_locked_posts(
    index: LibraryIndex, reader: JsonLibraryReader, *, unseen: bool, favorites: bool
) -> None:
    marked = _record('favorite')
    marked.media = {
        'video:old': replace(_media(MediaKind.boosty_video), added_at=EARLIER),
        'video:equal': _media(MediaKind.boosty_video),
        'video:new': replace(_media(MediaKind.external_video), added_at=LATER),
        'video:finished': replace(_media(MediaKind.boosty_video), added_at=LATER),
        'audio:new': replace(_media(MediaKind.audio), added_at=LATER),
        'image:missing-new': replace(
            _media(), added_at=LATER, status=MediaStatus.failed
        ),
        'image:missing-old': replace(
            _media(), added_at=EARLIER, status=MediaStatus.deleted
        ),
    }
    _write(
        index,
        marked,
        marks=PostMarks(
            seen_at=NOW,
            favorite=True,
            positions={'video:finished': PlaybackPosition(0, LATER)},
        ),
        access=PostAccess.locked,
    )
    unmarked = _record('unmarked')
    unmarked.media = {
        'video:unseen': _media(MediaKind.boosty_video),
        'video:done': _media(MediaKind.boosty_video),
    }
    _write(
        index,
        unmarked,
        marks=PostMarks(positions={'video:done': PlaybackPosition(0, NOW)}),
    )

    filters = MediaFilters(unseen_only=unseen, favorites_only=favorites)
    page = reader.list_media('writer', LibraryMediaView.video, filters)
    expected = {'video:old', 'video:equal', 'video:new', 'video:finished'}
    if unseen:
        expected = {'video:new'}
    if not favorites:
        expected |= {'video:unseen'} if unseen else {'video:unseen', 'video:done'}
    assert {item.media_id for item in page.items} == expected
    assert page.counts == MediaCounts(videos=len(expected), audio=1)
    assert page.missing == 0
    assert page.posts['favorite'].seen_at == NOW
    images = reader.list_media('writer', LibraryMediaView.image, filters)
    assert images.items == []
    assert images.posts == {}
    assert images.counts == page.counts
    assert images.missing == (1 if unseen else 2)


def test_complete_metadata_paths_thumbnails_playback_and_detached_snapshots(
    index: LibraryIndex, reader: JsonLibraryReader
) -> None:
    record = _record()
    record.media = {
        'image:one': _media(),
        'video:one': replace(
            _media(MediaKind.external_video, position=1),
            title='Lesson',
            filename='lesson.mp4',
            artist='Teacher',
            duration=timedelta(seconds=91.5),
            width=1920,
            height=1080,
            preview_path='media/preview.jpg',
        ),
        'file:zero': replace(_media(MediaKind.file, position=2), size=0),
    }
    _write(
        index, record, marks=PostMarks(positions={'video:one': PlaybackPosition(12.5)})
    )
    first = reader.list_media('writer', LibraryMediaView.all, MediaFilters())
    second = reader.list_media('writer', LibraryMediaView.all, MediaFilters())
    image, video = first.items
    assert image.thumbnail_path == 'writer/post/media/image-0.bin'
    assert video.thumbnail_path == 'writer/post/media/preview.jpg'
    assert video.entry == record.media['video:one']
    assert video.playback == PlaybackPosition(12.5)
    assert video.entry.path == 'media/external_video-1.bin'
    assert video.entry.preview_path == 'media/preview.jpg'
    assert video.folder == 'writer/post'
    assert video.created_at == NOW
    assert video.playback is not None
    video.entry.title = 'Changed'
    video.playback.seconds = 55
    first.items.clear()
    first.posts.clear()
    assert reader.list_media('writer', LibraryMediaView.all, MediaFilters()) == second
    assert (
        reader.list_media('writer', LibraryMediaView.file, MediaFilters())
        .items[0]
        .entry.size
        == 0
    )


def test_thumbnail_can_live_outside_the_post_folder(
    index: LibraryIndex, reader: JsonLibraryReader
) -> None:
    record = _record()
    record.media['image:one'] = _media()
    _write(index, record)
    engine = make_index_engine(index.path, writable=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                update(IndexMedia).values(
                    thumbnail_path='writer/.boosty-downloader/thumbs/picture.jpg'
                )
            )
    finally:
        engine.dispose()
    page = reader.list_media('writer', LibraryMediaView.image, MediaFilters())
    assert (
        page.items[0].thumbnail_path == 'writer/.boosty-downloader/thumbs/picture.jpg'
    )


def test_unknown_and_known_empty_authors_have_empty_media_pages(
    index: LibraryIndex, reader: JsonLibraryReader
) -> None:
    index.upsert_author(project_author(AuthorSource('empty', AuthorInfo('empty', NOW))))
    for author in ('empty', 'unknown'):
        for view in LibraryMediaView:
            assert reader.list_media(author, view, MediaFilters()) == LibraryMediaPage(
                [], {}, MediaCounts(), 0
            )


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('path', None),
        ('size', None),
        ('size', -1),
        ('size', float('inf')),
        ('size', 1.5),
        ('position', -1),
        ('position', 1.5),
        ('width', -1),
        ('width', float('inf')),
        ('width', 1.5),
        ('height', -1),
        ('height', float('inf')),
        ('height', 1.5),
        ('duration', -1),
        ('duration', float('inf')),
        ('duration', 1e30),
        ('playback_position', -1),
        ('playback_position', float('inf')),
        ('path', 'writer/post-other/media.bin'),
        ('path', 'writer/post/../media.bin'),
        ('path', '/writer/post/media.bin'),
        ('path', 'writer/post'),
        ('path', 'writer/post/media\\file.bin'),
        ('path', 'writer/post//file.bin'),
        ('path', 'writer/post/./file.bin'),
        ('path', 'writer/post/C:/file.bin'),
        ('path', 'writer/post/C:file.bin'),
        ('path', 'writer/post/file\0.bin'),
        ('preview_path', 'writer/another/preview.jpg'),
        ('preview_path', 'writer/post'),
        ('thumbnail_path', 'other/post/thumb.jpg'),
    ],
)
def test_corrupt_downloaded_metadata_is_an_error_not_a_dropped_item(
    index: LibraryIndex,
    reader: JsonLibraryReader,
    field: str,
    value: str | float | None,
) -> None:
    record = _record()
    record.media['image:one'] = _media()
    _write(index, record)
    engine = make_index_engine(index.path, writable=True)
    try:
        with engine.begin() as connection:
            connection.execute(update(IndexMedia).values({field: value}))
    finally:
        engine.dispose()
    with pytest.raises(LibraryReadError):
        reader.list_media('writer', LibraryMediaView.all, MediaFilters())


@pytest.mark.parametrize('folder', [None, 'writer', 'other/post', 'writer/../post'])
def test_corrupt_post_folder_is_an_error(
    index: LibraryIndex, reader: JsonLibraryReader, folder: str | None
) -> None:
    record = _record()
    record.media['image:one'] = _media()
    _write(index, record)
    engine = make_index_engine(index.path, writable=True)
    try:
        with engine.begin() as connection:
            connection.execute(update(IndexPost).values(folder=folder))
    finally:
        engine.dispose()
    with pytest.raises(LibraryReadError):
        reader.list_media('writer', LibraryMediaView.all, MediaFilters())


def test_items_counts_and_missing_share_snapshot_during_concurrent_mark_write(
    index: LibraryIndex, reader: JsonLibraryReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    record = _record()
    record.media = {
        'image:one': _media(),
        'image:missing': replace(_media(), status=MediaStatus.pending),
    }
    _write(index, record, marks=PostMarks(favorite=True))

    def read_with_concurrent_write(
        connection: Connection,
        author: str,
        view: LibraryMediaView,
        filters: MediaFilters,
    ) -> LibraryMediaPage:
        def write_between_queries(*_args: object) -> None:
            if trace.call_count != 2:
                return
            engine = make_index_engine(index.path, writable=True)
            try:
                with engine.begin() as writer:
                    writer.execute(update(IndexPost).values(favorite=False))
            finally:
                engine.dispose()

        trace = Mock(side_effect=write_between_queries)
        event.listen(connection, 'before_cursor_execute', trace)
        return media_queries.read_media(connection, author, view, filters)

    monkeypatch.setattr(reader_module, 'read_media', read_with_concurrent_write)
    filters = MediaFilters(favorites_only=True)
    page = reader.list_media('writer', LibraryMediaView.all, filters)
    assert len(page.items) == 1
    assert page.counts == MediaCounts(images=1)
    assert page.missing == 1
    assert page.posts['post'].favorite is True
    assert reader.list_media(
        'writer', LibraryMediaView.all, filters
    ) == LibraryMediaPage([], {}, MediaCounts(), 0)


@pytest.mark.parametrize('post_count', [1, 25])
def test_media_query_count_does_not_grow_with_post_count(
    index: LibraryIndex, post_count: int
) -> None:
    for number in range(post_count):
        record = _record(str(number))
        record.media['image:one'] = _media()
        _write(index, record)
    with index.connect() as connection:
        trace = Mock()
        event.listen(connection, 'before_cursor_execute', trace)
        page = media_queries.read_media(
            connection, 'writer', LibraryMediaView.image, MediaFilters()
        )
    assert len(page.items) == post_count
    assert trace.call_count == 2


def test_media_queries_do_not_read_canonical_records_or_inspect_files(
    root: Path,
    index: LibraryIndex,
    reader: JsonLibraryReader,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record()
    record.media['image:one'] = _media()
    _write(index, record)
    assert not (root / 'writer').exists()
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
        assert not path.is_relative_to(root / 'writer')
        return stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, 'read_bytes', guard_read)
    monkeypatch.setattr(Path, 'stat', guard_stat)
    monkeypatch.setattr(
        Path, 'iterdir', Mock(side_effect=AssertionError('Directory walk'))
    )
    page = reader.list_media('writer', LibraryMediaView.all, MediaFilters())
    assert len(page.items) == 1
    assert page.counts == MediaCounts(images=1)


def test_each_author_storage_equals_all_downloaded_sizes_in_corresponding_media_view(
    index: LibraryIndex, reader: JsonLibraryReader, inventory: StoredPost, root: Path
) -> None:
    locked = _record('retained-locked')
    locked.media = {
        kind.value: replace(_media(kind), removed_at=LATER) for kind in MediaKind
    }
    _write(index, locked, access=PostAccess.locked)
    other = _record('other-post', 'other')
    other.media = {kind.value: replace(_media(kind), size=100) for kind in MediaKind}
    _write(index, other)
    index.upsert_author(project_author(AuthorSource('empty', AuthorInfo('empty', NOW))))
    inventory.media['future:piece'] = _media()
    _write(index, inventory)
    engine = make_index_engine(index.path, writable=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                update(IndexMedia)
                .where(IndexMedia.media_id == 'future:piece')
                .values(kind='future')
            )
    finally:
        engine.dispose()
    assert not (root / 'writer').exists()
    views = {
        LibraryMediaView.image: 'images',
        LibraryMediaView.video: 'videos',
        LibraryMediaView.audio: 'audio',
        LibraryMediaView.file: 'files',
    }
    for author in reader.authors():
        assert reader.author(author.author) == author
        for view, bucket in views.items():
            items = reader.list_media(author.author, view, MediaFilters()).items
            sizes = [item.entry.size for item in items]
            assert all(size is not None for size in sizes)
            assert sum(size for size in sizes if size is not None) == getattr(
                author.storage, bucket
            )
            assert all(item.media_id != 'future:piece' for item in items)
