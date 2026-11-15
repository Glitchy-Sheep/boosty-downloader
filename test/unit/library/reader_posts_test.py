"""Post browsing rows preserve filtered totals and current inventory semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.domain.library import (
    LibraryContentKind,
    MediaCounts,
    MonthCount,
    PostAccess,
    PostFilters,
    PostOrder,
)
from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.domain.stored_post import (
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=1)


@pytest.fixture
def store(tmp_path: Path) -> JsonPostStore:
    initialize_library(tmp_path)
    return JsonPostStore(tmp_path)


def _record(post_id: str, created_at: datetime = NOW) -> StoredPost:
    return StoredPost(
        PostMetadata(
            post_id,
            'writer',
            f'https://boosty.to/writer/posts/{post_id}',
            'Lesson',
            created_at,
            created_at,
        ),
        PostSync(NOW, NOW),
    )


def _save(store: JsonPostStore, record: StoredPost) -> str:
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    return folder


def _reader(root: Path) -> JsonLibraryReader:
    result = JsonLibraryReader(root)
    result.prepare()
    return result


def _ids(reader: JsonLibraryReader, filters: PostFilters) -> list[str]:
    return [row.overview.post.id for row in reader.list_posts('writer', filters).rows]


@pytest.mark.parametrize('order', list(PostOrder))
def test_filtered_months_total_and_full_id_ties(
    tmp_path: Path, store: JsonPostStore, order: PostOrder
) -> None:
    for post_id, month in [
        ('abcdefgh-z', 11),
        ('abcdefgh-a', 11),
        ('ijklmnop-old', 10),
        ('qrstuvwx-skip', 9),
    ]:
        record = _record(post_id, NOW.replace(month=month))
        record.post.tags = ['selected', 'selected'] if month != 9 else []
        _save(store, record)
    result = _reader(tmp_path).list_posts(
        'writer', PostFilters(tag='selected', order=order)
    )
    expected = ['abcdefgh-z', 'abcdefgh-a', 'ijklmnop-old']
    months = [MonthCount('2026-11', 2), MonthCount('2026-10', 1)]
    if order is PostOrder.oldest:
        expected.reverse()
        months.reverse()
    assert [row.overview.post.id for row in result.rows] == expected
    assert result.months == months
    assert result.total == 3


def test_empty_selection_has_no_rows_months_or_total(
    tmp_path: Path, store: JsonPostStore
) -> None:
    _save(store, _record('abcdefgh-one'))
    reader = _reader(tmp_path)
    for author, filters in [
        ('missing', PostFilters()),
        ('writer', PostFilters(favorites_only=True)),
    ]:
        result = reader.list_posts(author, filters)
        assert result.rows == []
        assert result.months == []
        assert result.total == 0


def test_row_counts_current_inventory_and_keeps_viewing_fields(
    tmp_path: Path, store: JsonPostStore
) -> None:
    record = _record('abcdefgh-one')
    for kind in MediaKind:
        for status in MediaStatus:
            record.media[f'{kind.value}:{status.value}'] = MediaEntry(
                kind,
                status,
                LATER,
                len(record.media),
                path=f'{kind.value}-{status.value}.bin',
                size=10,
            )
    record.media['file:removed'] = MediaEntry(
        MediaKind.file,
        MediaStatus.downloaded,
        NOW,
        99,
        removed_at=LATER,
        path='removed.zip',
        size=10,
    )
    _save(store, record)
    JsonPostMarks(tmp_path).save_marks(
        'writer', record.post.id, PostMarks(seen_at=NOW, favorite=True)
    )
    row = _reader(tmp_path).list_posts('writer', PostFilters()).rows[0]
    assert row.counts == MediaCounts(images=5, videos=10, files=5, audio=5)
    assert row.missing_media == 20
    assert row.seen_at == NOW
    assert row.favorite is True
    assert row.pieces_added_at == LATER
    assert row.match is None


@pytest.mark.parametrize('kind', list(MediaKind))
@pytest.mark.parametrize('status', [MediaStatus.pending, MediaStatus.downloaded])
def test_removed_pieces_do_not_count_or_match_kind_and_incomplete(
    tmp_path: Path, store: JsonPostStore, kind: MediaKind, status: MediaStatus
) -> None:
    record = _record('abcdefgh-one')
    record.media[f'{kind.value}:removed'] = MediaEntry(
        kind, status, NOW, 0, removed_at=LATER, path='piece.bin', size=10
    )
    _save(store, record)
    reader = _reader(tmp_path)
    row = reader.list_posts('writer', PostFilters()).rows[0]
    assert row.counts == MediaCounts()
    assert row.missing_media == 0
    assert _ids(reader, PostFilters(incomplete_only=True)) == []
    assert all(
        not _ids(reader, PostFilters(kind=content_kind))
        for content_kind in LibraryContentKind
    )


def test_locked_only_counts_remote_kinds_without_inventing_missing_media(
    tmp_path: Path, store: JsonPostStore
) -> None:
    record = _record('abcdefgh-locked')
    record.post.content_counters = {
        'image': 2,
        'ok_video': 3,
        'video': 4,
        'file': 5,
        'audio': 6,
    }
    store.save_locked_post(LockedPost(record.post, NOW))
    reader = _reader(tmp_path)
    row = reader.list_posts('writer', PostFilters(locked_only=True)).rows[0]
    assert row.counts == MediaCounts(images=2, videos=7, files=5, audio=6)
    assert row.missing_media == 0
    assert row.overview.access is PostAccess.locked
    assert _ids(reader, PostFilters(incomplete_only=True)) == []
    assert _ids(reader, PostFilters(locked_only=True, unseen_only=True)) == []


def test_retained_locked_body_is_incomplete_from_saved_inventory(
    tmp_path: Path, store: JsonPostStore
) -> None:
    record = _record('abcdefgh-retained')
    record.media['audio:pending'] = MediaEntry(
        MediaKind.audio, MediaStatus.pending, NOW, 0
    )
    _save(store, record)
    locked = replace(record.post, content_counters={'image': 99})
    store.save_locked_post(LockedPost(locked, LATER))
    reader = _reader(tmp_path)
    filters = PostFilters(
        locked_only=True, incomplete_only=True, kind=LibraryContentKind.audio
    )
    row = reader.list_posts('writer', filters).rows[0]
    assert row.counts == MediaCounts(audio=1)
    assert row.missing_media == 1
    assert _ids(reader, replace(filters, kind=LibraryContentKind.image)) == []


@pytest.mark.parametrize('status', list(MediaStatus))
def test_incomplete_filter_includes_each_current_non_downloaded_status(
    tmp_path: Path, store: JsonPostStore, status: MediaStatus
) -> None:
    record = _record('abcdefgh-one')
    record.media['file:one'] = MediaEntry(
        MediaKind.file, status, NOW, 0, path='one.zip', size=10
    )
    _save(store, record)
    expected = [] if status is MediaStatus.downloaded else [record.post.id]
    assert _ids(_reader(tmp_path), PostFilters(incomplete_only=True)) == expected


def test_favorites_and_all_post_filters_compose(
    tmp_path: Path, store: JsonPostStore
) -> None:
    for post_id in ['abcdefgh-match', 'ijklmnop-other']:
        record = _record(post_id)
        record.post.title = 'Shader lesson'
        record.post.tags = ['exact', 'exact']
        record.media['audio:one'] = MediaEntry(
            MediaKind.audio, MediaStatus.pending, LATER, 0
        )
        _save(store, record)
    JsonPostMarks(tmp_path).save_marks(
        'writer', 'abcdefgh-match', PostMarks(seen_at=NOW, favorite=True)
    )
    reader = _reader(tmp_path)
    filters = PostFilters(
        text='shad less',
        tag='exact',
        kind=LibraryContentKind.audio,
        favorites_only=True,
        unseen_only=True,
        incomplete_only=True,
        order=PostOrder.oldest,
    )
    result = reader.list_posts('writer', filters)
    assert _ids(reader, filters) == ['abcdefgh-match']
    assert result.total == 1
    assert result.months == [MonthCount('2026-11', 1)]
    assert _ids(reader, replace(filters, locked_only=True)) == []
    assert _ids(reader, replace(filters, tag='Exact')) == []
    reader.save_marks(
        'writer', 'abcdefgh-match', PostMarks(seen_at=LATER, favorite=True)
    )
    assert _ids(reader, filters) == []


def test_row_cover_is_relative_and_each_read_is_independent(
    tmp_path: Path, store: JsonPostStore
) -> None:
    record = _record('abcdefgh-one')
    record.post.tags = ['one']
    record.media['image:cover'] = MediaEntry(
        MediaKind.image, MediaStatus.downloaded, NOW, 0, path='cover.jpg', size=5
    )
    record.blocks.append(MediaBlock('image:cover'))
    folder = _save(store, record)
    (tmp_path / folder / 'cover.jpg').write_bytes(b'image')
    reader = _reader(tmp_path)
    first = reader.list_posts('writer', PostFilters())
    second = reader.list_posts('writer', PostFilters())
    assert first.rows[0].cover_path == f'{folder}/cover.jpg'
    first.rows[0].overview.post.tags.clear()
    first.rows.clear()
    first.months.clear()
    assert second.rows[0].overview.post.tags == ['one']
    assert second.months == [MonthCount('2026-11', 1)]
    assert reader.list_posts('writer', PostFilters()) == second
