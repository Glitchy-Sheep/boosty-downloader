"""Author summaries use indexed access, viewing state and retained media bytes."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from sqlalchemy import event, update

from boosty_downloader.domain.library import (
    AuthorCounts,
    LibraryAuthor,
    LibraryPost,
    MediaStorage,
    PostAccess,
    PostFilters,
    PostOverview,
    TagCount,
)
from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library._index_engine import make_index_engine
from boosty_downloader.infrastructure.library._index_models import IndexMedia
from boosty_downloader.infrastructure.library._reader_authors import (
    has_author,
    read_author,
    read_authors,
)
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
def reader(root: Path, index: LibraryIndex) -> JsonLibraryReader:  # noqa: ARG001 - prepare index fixture
    return JsonLibraryReader(root)


def _record(post_id: str, author: str = 'writer') -> StoredPost:
    return StoredPost(
        PostMetadata(
            post_id,
            author,
            f'https://boosty.to/{author}/posts/{post_id}',
            'Lesson',
            NOW,
            NOW,
        ),
        PostSync(NOW, NOW),
    )


def _write(
    index: LibraryIndex,
    record: StoredPost,
    *,
    access: PostAccess = PostAccess.open,
    marks: PostMarks | None = None,
) -> None:
    source = PostSource(
        LibraryPost(
            PostOverview(record.post, access),
            record,
            f'{record.post.author}/{record.post.id}',
        ),
        marks=marks if marks is not None else PostMarks(),
    )
    index.upsert_post(project_post(source))


def _media(kind: MediaKind = MediaKind.file, size: int | None = 23) -> MediaEntry:
    return MediaEntry(
        kind,
        MediaStatus.downloaded,
        NOW,
        0,
        path='files/media.mp4',
        size=size,
        filename='media.mp4',
    )


def _trace_queries(connection: Connection) -> Mock:
    trace = Mock()
    event.listen(connection, 'before_cursor_execute', trace)
    return trace


def test_author_counts_include_locked_favorites_and_unseen_piece_updates(
    index: LibraryIndex, reader: JsonLibraryReader
) -> None:
    _write(index, _record('unseen'), marks=PostMarks(favorite=True))
    _write(index, _record('seen'), marks=PostMarks(seen_at=NOW))
    added = _record('added')
    added.media['file:new'] = replace(_media(), added_at=LATER)
    _write(index, added, marks=PostMarks(seen_at=NOW, favorite=True))
    equal = _record('equal')
    equal.media['file:same-time'] = _media()
    _write(index, equal, marks=PostMarks(seen_at=NOW))
    _write(
        index,
        _record('retained-locked'),
        access=PostAccess.locked,
        marks=PostMarks(favorite=True),
    )
    locked = _record('locked-only')
    locked.post.content_counters = {'video': 10}
    index.upsert_post(
        project_post(
            PostSource(LibraryPost(PostOverview(locked.post, PostAccess.locked)))
        )
    )
    _write(index, _record('unrelated', 'other'), marks=PostMarks(favorite=True))

    author = reader.author('writer')
    assert author is not None
    assert author.counts == AuthorCounts(posts=6, locked=2, unseen=2, favorites=3)
    assert (
        author.counts.unseen
        == reader.list_posts('writer', PostFilters(unseen_only=True)).total
    )
    assert (
        author.counts.favorites
        == reader.list_posts('writer', PostFilters(favorites_only=True)).total
    )
    assert (
        author.counts.locked
        == reader.list_posts('writer', PostFilters(locked_only=True)).total
    )


def test_known_empty_and_missing_authors_have_distinct_results(
    index: LibraryIndex, reader: JsonLibraryReader
) -> None:
    info = AuthorInfo('empty', NOW, title='No saved posts', remote_post_count=10)
    index.upsert_author(project_author(AuthorSource('empty', info)))

    assert reader.has_author('empty') is True
    assert reader.author('empty') == LibraryAuthor('empty', info)
    assert reader.authors() == [LibraryAuthor('empty', info)]
    assert reader.tags('empty') == []
    assert reader.has_author('missing') is False
    assert reader.author('missing') is None
    assert reader.tags('missing') == []


def test_empty_library_has_no_author_summaries(reader: JsonLibraryReader) -> None:
    assert reader.authors() == []
    assert reader.author('writer') is None
    assert reader.has_author('writer') is False
    assert reader.tags('writer') == []


def test_author_metadata_snapshots_are_complete_and_independent(
    index: LibraryIndex, reader: JsonLibraryReader
) -> None:
    info = AuthorInfo(
        'writer',
        NOW,
        title='Lessons',
        owner_name='Teacher',
        description='First paragraph.\n\nSecond paragraph.',
        avatar_path='.boosty/avatar.jpg',
        cover_path='.boosty/cover.jpg',
        remote_post_count=99,
    )
    index.upsert_author(project_author(AuthorSource('writer', info)))
    first = reader.author('writer')
    second = reader.authors()[0]
    assert first == second == LibraryAuthor('writer', info)
    assert first is not None
    assert first.info is not None
    first.info.description = 'Changed'
    assert second.info == info
    assert reader.author('writer') == second


@pytest.mark.parametrize('status', list(MediaStatus))
@pytest.mark.parametrize('removed', [False, True])
def test_storage_counts_only_downloaded_bytes_even_after_removal(
    index: LibraryIndex,
    reader: JsonLibraryReader,
    status: MediaStatus,
    *,
    removed: bool,
) -> None:
    record = _record('statuses')
    record.media['file:one'] = replace(
        _media(), status=status, removed_at=LATER if removed else None
    )
    _write(index, record)

    author = reader.author('writer')
    assert author is not None
    assert author.storage == MediaStorage(
        files=23 if status is MediaStatus.downloaded else 0
    )


def test_storage_combines_video_sources_and_uses_kind_instead_of_file_suffix(
    index: LibraryIndex, reader: JsonLibraryReader
) -> None:
    record = _record('kinds')
    record.media = {
        'image:one': _media(MediaKind.image, 11),
        'boosty_video:one': _media(MediaKind.boosty_video, 13),
        'external_video:one': _media(MediaKind.external_video, 17),
        'file:video-attachment': _media(MediaKind.file, 19),
        'audio:one': _media(MediaKind.audio, 23),
    }
    _write(index, record)
    extra = _record('another-post')
    extra.media['image:extra'] = _media(MediaKind.image, 7)
    _write(index, extra, access=PostAccess.locked)
    unrelated = _record('unrelated', 'other')
    unrelated.media['image:unrelated'] = _media(MediaKind.image, 1000)
    _write(index, unrelated)

    author = reader.author('writer')
    assert author is not None
    assert author.storage == MediaStorage(images=18, videos=30, files=19, audio=23)
    assert author == next(item for item in reader.authors() if item.author == 'writer')


def test_storage_ignores_unrecorded_sizes_and_unknown_kinds(
    index: LibraryIndex, reader: JsonLibraryReader
) -> None:
    record = _record('unsized')
    record.media = {
        'file:unsized': _media(size=None),
        'file:future-kind': _media(size=100),
        'file:empty': _media(size=0),
    }
    _write(index, record)
    engine = make_index_engine(index.path, writable=True)
    try:
        with engine.begin() as connection:
            connection.execute(
                update(IndexMedia)
                .where(IndexMedia.media_id == 'file:future-kind')
                .values(kind='future-kind')
            )
    finally:
        engine.dispose()

    author = reader.author('writer')
    assert author is not None
    assert author.storage == MediaStorage()


def test_author_queries_read_no_canonical_records_or_physical_media(
    root: Path,
    index: LibraryIndex,
    reader: JsonLibraryReader,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = _record('index-only')
    record.media['file:absent'] = _media(size=123)
    _write(index, record)
    assert not (root / 'writer').exists()
    read_bytes = Path.read_bytes
    stat = Path.stat

    def guard_read(path: Path) -> bytes:
        assert path.name not in {
            'author.json',
            'locked.json',
            'post.json',
            'viewer.json',
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
    assert reader.has_author('writer') is True
    author = reader.author('writer')
    assert author is not None
    assert author.storage == MediaStorage(files=123)
    assert reader.authors() == [author]
    assert reader.tags('writer') == []


def test_tags_count_distinct_posts_preserve_exact_values_and_scope_to_author(
    index: LibraryIndex, reader: JsonLibraryReader
) -> None:
    first = _record('first')
    first.post.tags = ['lesson', 'Lesson', 'lesson', ' ёлка', 'ёлка', 'елка']
    _write(index, first)
    second = _record('second')
    second.post.tags = ['lesson', 'lesson', 'ёлка']
    index.upsert_post(
        project_post(
            PostSource(LibraryPost(PostOverview(second.post, PostAccess.locked)))
        )
    )
    other = _record('other', 'other')
    other.post.tags = ['lesson', 'unrelated']
    _write(index, other)

    assert reader.tags('writer') == [
        TagCount(' ёлка', 1),
        TagCount('Lesson', 1),
        TagCount('lesson', 2),
        TagCount('елка', 1),
        TagCount('ёлка', 2),
    ]


@pytest.mark.parametrize('author_count', [1, 25])
def test_all_author_query_count_is_constant(
    index: LibraryIndex, author_count: int
) -> None:
    for number in range(author_count):
        _write(index, _record('post', f'writer-{number:02}'))
    with index.connect() as connection:
        trace = _trace_queries(connection)
        authors = read_authors(connection)

    assert len(authors) == author_count
    assert [item.author for item in authors] == sorted(item.author for item in authors)
    assert trace.call_count == 3
    statements = [str(call.args[2]).upper() for call in trace.call_args_list]
    assert sum('FROM AUTHORS' in statement for statement in statements) == 1
    assert sum('FROM POSTS' in statement for statement in statements) == 1
    assert sum('FROM MEDIA' in statement for statement in statements) == 1


def test_single_author_queries_are_scoped_by_full_identity(index: LibraryIndex) -> None:
    _write(index, _record('post', 'writer'))
    _write(index, _record('post', 'writer-other'))
    with index.connect() as connection:
        trace = _trace_queries(connection)
        author = read_author(connection, 'writer')

    assert author == LibraryAuthor('writer', counts=AuthorCounts(posts=1, unseen=1))
    assert trace.call_count == 3
    for call in trace.call_args_list:
        statement = str(call.args[2]).upper()
        assert 'WHERE' in statement
        assert '.AUTHOR = ?' in statement
        assert 'writer' in call.args[3]


def test_has_author_and_missing_author_query_only_author_table(
    index: LibraryIndex,
) -> None:
    _write(index, _record('post'))
    with index.connect() as connection:
        trace = _trace_queries(connection)
        assert has_author(connection, 'writer') is True
        assert has_author(connection, 'write') is False
        assert read_author(connection, 'missing') is None

    assert trace.call_count == 3
    for call in trace.call_args_list:
        statement = str(call.args[2]).upper()
        assert 'FROM AUTHORS' in statement
        assert 'POSTS' not in statement
        assert 'MEDIA' not in statement
