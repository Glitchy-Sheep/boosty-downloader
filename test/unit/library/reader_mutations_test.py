"""Canonical marks survive retries, concurrent changes and stale indexed state."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
from os import utime
from shutil import copytree, rmtree
from threading import Barrier
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from sqlalchemy import select
from support.viewer_read_library import (
    AUDIO_ID,
    EARLIER,
    LOCKED_ID,
    NOW,
    OLD_ID,
    POST_ID,
    TEXT_ID,
    ReadLibrary,
    make_library,
)

from boosty_downloader.domain.library import PostAccess, PostFilters, PostOrder
from boosty_downloader.domain.library_errors import (
    LibraryMarkConflictError,
    LibraryWriteError,
)
from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.library_mutations import BulkMarkProgress, MediaIdentity
from boosty_downloader.domain.stored_post import LockedPost
from boosty_downloader.infrastructure.library import _index_marks as index_marks
from boosty_downloader.infrastructure.library import _reader_mutations as mutations
from boosty_downloader.infrastructure.library import index as index_module
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.json_store import write_post_record
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.domain.library import LibraryAuthor
    from boosty_downloader.infrastructure.library.index_sources import PostSource


def _marks(library: ReadLibrary, post_id: str) -> PostMarks:
    result = library.reader.get_marks('writer', post_id)
    assert result is not None
    return result


def _author(library: ReadLibrary) -> LibraryAuthor:
    result = library.reader.author('writer')
    assert result is not None
    return result


@pytest.fixture
def library(tmp_path: Path) -> ReadLibrary:
    built = make_library(tmp_path / 'library')
    return replace(built, reader=JsonLibraryReader(built.root, clock=lambda: NOW))


def test_single_changes_return_fresh_state_and_preserve_other_marks(
    library: ReadLibrary,
) -> None:
    result = library.reader.set_seen('writer', POST_ID, seen=True)
    assert result is not None
    assert result.post.seen_at == NOW
    assert result.post.favorite
    assert result.author.counts.unseen == 1
    favorite = library.reader.set_favorite('writer', POST_ID, favorite=False)
    assert favorite is not None
    assert not favorite.post.favorite
    assert favorite.post.seen_at == NOW
    assert favorite.author.counts.favorites == 0
    assert library.reader.get_marks('writer', POST_ID) == PostMarks(
        seen_at=NOW, favorite=False, positions={AUDIO_ID: PlaybackPosition(34)}
    )


def test_noop_preserves_canonical_bytes_and_mtime(library: ReadLibrary) -> None:
    path = library.root / library.folder / 'viewer.json'
    before = path.read_bytes(), path.stat().st_mtime_ns
    result = library.reader.set_favorite('writer', POST_ID, favorite=True)
    assert result is not None
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize('post_id', [POST_ID, LOCKED_ID])
def test_locked_posts_reject_seen_and_favorite(
    library: ReadLibrary, post_id: str
) -> None:
    if post_id == POST_ID:
        library.store.save_locked_post(LockedPost(library.record.post, NOW))
    before = library.reader.get_marks('writer', post_id)
    with pytest.raises(LibraryMarkConflictError):
        library.reader.set_seen('writer', post_id, seen=True)
    with pytest.raises(LibraryMarkConflictError):
        library.reader.set_favorite('writer', post_id, favorite=False)
    assert library.reader.get_marks('writer', post_id) == before


def test_unknown_resources_return_none(library: ReadLibrary) -> None:
    assert library.reader.set_seen('missing', POST_ID, seen=True) is None
    assert library.reader.set_favorite('writer', 'missing', favorite=True) is None
    assert (
        library.reader.set_position('writer', MediaIdentity(POST_ID, 'missing'), 2, 90)
        is None
    )
    assert (
        library.reader.set_position('writer', MediaIdentity(LOCKED_ID, AUDIO_ID), 2, 90)
        is None
    )
    assert library.reader.set_seen_many('missing', PostFilters(), seen=True) is None


@pytest.mark.parametrize(
    'media_id', ['image:cover', 'boosty_video:pending', 'file:removed', 'file:never']
)
def test_known_unplayable_media_cannot_acquire_positions(
    library: ReadLibrary, media_id: str
) -> None:
    before = library.reader.get_marks('writer', POST_ID)
    with pytest.raises(LibraryMarkConflictError):
        library.reader.set_position('writer', MediaIdentity(POST_ID, media_id), 5, 90)
    assert library.reader.get_marks('writer', POST_ID) == before


def test_retained_removed_and_locked_media_keep_playback(library: ReadLibrary) -> None:
    media_id = 'external_video:https://example.test/watch?a=b:c'
    library.store.save_locked_post(LockedPost(library.record.post, NOW))
    result = library.reader.set_position(
        'writer', MediaIdentity(POST_ID, media_id), 22.8, 24
    )
    assert result is not None
    assert result.entry.removed_at == NOW
    assert result.playback == PlaybackPosition(0, NOW)
    assert result.folder == library.folder
    result.entry.title = 'Changed by caller'
    assert result.playback is not None
    result.playback.seconds = 13
    detail = library.reader.post('writer', POST_ID)
    assert detail is not None
    assert detail.content.overview.access is PostAccess.locked
    assert detail.marks.positions[media_id] == PlaybackPosition(0, NOW)
    assert detail.marks.positions[AUDIO_ID] == PlaybackPosition(34)


def test_deleted_folder_is_not_recreated(library: ReadLibrary) -> None:
    folder = library.root / library.folder
    rmtree(folder)
    assert library.reader.set_seen('writer', POST_ID, seen=True) is None
    assert (
        library.reader.set_position('writer', MediaIdentity(POST_ID, AUDIO_ID), 4, 90)
        is None
    )
    assert not folder.exists()


def test_locked_observation_remains_known_after_its_folder_disappears(
    library: ReadLibrary,
) -> None:
    library.store.save_locked_post(LockedPost(library.record.post, NOW))
    folder = library.root / library.folder
    rmtree(folder)
    with pytest.raises(LibraryMarkConflictError):
        library.reader.set_seen('writer', POST_ID, seen=True)
    with pytest.raises(LibraryMarkConflictError):
        library.reader.set_favorite('writer', POST_ID, favorite=False)
    assert (
        library.reader.set_position('writer', MediaIdentity(POST_ID, AUDIO_ID), 12, 90)
        is None
    )
    assert not folder.exists()


def test_corrupt_marks_are_not_replaced(library: ReadLibrary) -> None:
    path = library.root / library.folder / 'viewer.json'
    path.write_bytes(b'{broken')
    with pytest.raises(LibraryWriteError):
        library.reader.set_favorite('writer', POST_ID, favorite=False)
    assert path.read_bytes() == b'{broken'


def test_write_failure_does_not_change_index_or_canonical_marks(
    library: ReadLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = library.reader.get_marks('writer', POST_ID)
    indexed = library.reader.list_posts('writer', PostFilters())
    monkeypatch.setattr(
        mutations, 'write_atomically', Mock(side_effect=PermissionError('denied'))
    )
    with pytest.raises(LibraryWriteError) as failure:
        library.reader.set_favorite('writer', POST_ID, favorite=False)
    assert isinstance(failure.value.__cause__, PermissionError)
    assert library.reader.get_marks('writer', POST_ID) == before
    assert library.reader.list_posts('writer', PostFilters()) == indexed


def test_noop_retry_repairs_index_after_canonical_publication(
    library: ReadLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = LibraryIndex.update_marks
    monkeypatch.setattr(
        LibraryIndex, 'update_marks', Mock(side_effect=OSError('index failed'))
    )
    with pytest.raises(LibraryWriteError):
        library.reader.set_favorite('writer', POST_ID, favorite=False)
    assert _marks(library, POST_ID).favorite is False
    assert _author(library).counts.favorites == 1
    path = library.root / library.folder / 'viewer.json'
    before = path.read_bytes(), path.stat().st_mtime_ns
    monkeypatch.setattr(LibraryIndex, 'update_marks', original)
    result = library.reader.set_favorite('writer', POST_ID, favorite=False)
    assert result is not None
    assert result.author.counts.favorites == 0
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert library.reader.prepare().posts_updated == 0


def test_concurrent_changes_preserve_every_independent_field(
    library: ReadLibrary,
) -> None:
    ready = Barrier(4)
    removed = 'external_video:https://example.test/watch?a=b:c'

    def change(kind: int) -> None:
        ready.wait(timeout=10)
        match kind:
            case 0:
                library.reader.set_seen('writer', POST_ID, seen=True)
            case 1:
                library.reader.set_favorite('writer', POST_ID, favorite=False)
            case 2:
                library.reader.set_position(
                    'writer', MediaIdentity(POST_ID, AUDIO_ID), 8, 90
                )
            case 3:
                library.reader.set_position(
                    'writer', MediaIdentity(POST_ID, removed), 12, 90
                )
            case _:
                raise AssertionError(kind)

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(change, range(4)))
    assert library.reader.get_marks('writer', POST_ID) == PostMarks(
        seen_at=NOW,
        favorite=False,
        positions={AUDIO_ID: PlaybackPosition(8), removed: PlaybackPosition(12)},
    )


def test_bulk_uses_a_fixed_unseen_selection_and_reports_real_changes(
    library: ReadLibrary,
) -> None:
    progress: list[BulkMarkProgress] = []
    count = library.reader.set_seen_many(
        'writer', PostFilters(unseen_only=True), seen=True, progress=progress.append
    )
    assert count == 2
    assert progress == [
        BulkMarkProgress(2, 0, 0),
        BulkMarkProgress(2, 1, 1),
        BulkMarkProgress(2, 2, 2),
    ]
    assert library.reader.list_posts('writer', PostFilters(unseen_only=True)).total == 0
    assert library.reader.set_seen_many('writer', PostFilters(), seen=True) == 0
    assert (
        library.reader.set_seen_many('writer', PostFilters(locked_only=True), seen=True)
        == 0
    )


@pytest.mark.parametrize('order', [PostOrder.oldest, PostOrder.newest])
def test_bulk_combines_search_tag_favorite_and_order(
    library: ReadLibrary, order: PostOrder
) -> None:
    filters = PostFilters(text='shader', tag='lesson', favorites_only=True, order=order)
    assert library.reader.set_seen_many('writer', filters, seen=False) == 1
    assert _marks(library, POST_ID).seen_at is None
    assert _marks(library, OLD_ID).seen_at == NOW
    assert _marks(library, TEXT_ID).seen_at is None


def test_bulk_skips_a_fresh_locked_post_and_performs_no_author_scan(
    library: ReadLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    library.store.save_locked_post(LockedPost(library.record.post, NOW))
    monkeypatch.setattr(
        JsonPostRecords, 'find_post', Mock(side_effect=AssertionError('author scan'))
    )
    progress: list[BulkMarkProgress] = []
    assert (
        library.reader.set_seen_many(
            'writer', PostFilters(), seen=True, progress=progress.append
        )
        == 1
    )
    assert progress[-1] == BulkMarkProgress(3, 3, 1)
    detail = library.reader.post('writer', POST_ID)
    assert detail is not None
    assert detail.marks.seen_at == EARLIER


def test_bulk_failure_keeps_saved_prefix_and_retry_repairs_it(
    library: ReadLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = LibraryIndex.update_marks
    calls = 0

    def fail_second(index: LibraryIndex, post: PostSource) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            message = 'second update failed'
            raise OSError(message)
        original(index, post)

    monkeypatch.setattr(LibraryIndex, 'update_marks', fail_second)
    progress: list[BulkMarkProgress] = []
    with pytest.raises(LibraryWriteError):
        library.reader.set_seen_many(
            'writer', PostFilters(), seen=True, progress=progress.append
        )
    assert progress == [BulkMarkProgress(3, 0, 0), BulkMarkProgress(3, 1, 1)]
    assert _marks(library, POST_ID).seen_at == NOW
    assert _marks(library, TEXT_ID).seen_at == NOW
    monkeypatch.setattr(LibraryIndex, 'update_marks', original)
    assert library.reader.set_seen_many('writer', PostFilters(), seen=True) == 0
    assert _author(library).counts.unseen == 0


def test_reused_custom_index_cannot_mutate_the_original_library(
    library: ReadLibrary, tmp_path: Path
) -> None:
    index = tmp_path / 'cache' / 'index.db'
    reader = JsonLibraryReader(library.root, index_path=index)
    reader.prepare()
    copied = tmp_path / 'copied'
    copytree(library.root, copied)
    JsonLibraryReader(copied, index_path=index).prepare()
    original = JsonPostMarks(library.root).get_marks('writer', POST_ID)
    with pytest.raises(LibraryWriteError):
        reader.set_favorite('writer', POST_ID, favorite=False)
    assert JsonPostMarks(library.root).get_marks('writer', POST_ID) == original


def test_mark_only_change_does_not_rewrite_content_projection(
    library: ReadLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        index_module,
        'write_posts',
        Mock(side_effect=AssertionError('content rewritten')),
    )
    assert library.reader.set_favorite('writer', POST_ID, favorite=False) is not None
    assert (
        library.reader.set_position('writer', MediaIdentity(POST_ID, AUDIO_ID), 11, 90)
        is not None
    )
    assert (
        library.reader.list_posts(
            'writer', PostFilters(text='shader', tag='lesson')
        ).total
        == 1
    )
    assert library.reader.prepare().posts_updated == 0


def test_changed_content_uses_full_projection_even_for_noop_mark(
    library: ReadLibrary,
) -> None:
    library.record.post.title = 'Brand new title'
    library.record.post.tags = ['new-tag']
    library.store.save_post(library.folder, library.record)
    result = library.reader.set_favorite('writer', POST_ID, favorite=True)
    assert result is not None
    rows = library.reader.list_posts(
        'writer', PostFilters(text='brand', tag='new-tag')
    ).rows
    assert len(rows) == 1
    assert rows[0].overview.post.title == 'Brand new title'


def test_changed_locked_metadata_uses_full_projection_for_playback(
    library: ReadLibrary,
) -> None:
    library.store.save_locked_post(LockedPost(library.record.post, NOW))
    identity = MediaIdentity(POST_ID, AUDIO_ID)
    library.reader.set_position('writer', identity, 11, 90)
    library.record.post.title = 'Changed locked title'
    library.record.post.tags = ['locked-tag']
    library.record.post.tier_price_rub = 321
    library.store.save_locked_post(LockedPost(library.record.post, NOW))
    library.reader.set_position('writer', identity, 12, 90)
    rows = library.reader.list_posts('writer', PostFilters(tag='locked-tag')).rows
    assert len(rows) == 1
    assert rows[0].overview.post.title == 'Changed locked title'
    assert rows[0].overview.post.tier_price_rub == 321
    assert rows[0].overview.access is PostAccess.locked


def test_recomputed_cover_updates_when_content_and_marks_are_unchanged(
    library: ReadLibrary,
) -> None:
    image = library.record.media['image:cover']
    assert image.path is not None
    (library.root / library.folder / image.path).unlink()
    result = library.reader.set_favorite('writer', POST_ID, favorite=True)
    assert result is not None
    assert result.post.cover_path is None
    indexed = next(
        row
        for row in library.reader.list_posts('writer', PostFilters()).rows
        if row.overview.post.id == POST_ID
    )
    assert indexed.cover_path is None


def test_mark_projection_failure_rolls_back_fingerprint_and_positions(
    library: ReadLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    index = LibraryIndex(library.root)
    query = select(IndexPost.viewer_json_mtime_ns, IndexPost.viewer_json_size).where(
        IndexPost.post_id == POST_ID
    )
    position_query = select(IndexMedia.playback_position).where(
        IndexMedia.post_id == POST_ID, IndexMedia.media_id == AUDIO_ID
    )
    with index.connect() as connection:
        before = connection.execute(query).one()
    identity = MediaIdentity(POST_ID, AUDIO_ID)
    with monkeypatch.context() as failure:
        failure.setattr(
            index_marks,
            '_write_positions',
            Mock(side_effect=OSError('media update failed')),
        )
        with pytest.raises(LibraryWriteError):
            library.reader.set_position('writer', identity, 14, 90)
    assert _marks(library, POST_ID).positions[AUDIO_ID].seconds == 14
    with index.connect() as connection:
        assert connection.execute(query).one() == before
        assert connection.scalar(position_query) == 34
    library.reader.set_position('writer', identity, 14, 90)
    with index.connect() as connection:
        assert connection.execute(query).one() != before
        assert connection.scalar(position_query) == 14
    assert library.reader.prepare().posts_updated == 0


def test_noop_repairs_externally_removed_positions(library: ReadLibrary) -> None:
    JsonPostMarks(library.root).save_marks('writer', POST_ID, PostMarks(favorite=True))
    library.reader.set_favorite('writer', POST_ID, favorite=True)
    with LibraryIndex(library.root).connect() as connection:
        positions = connection.scalars(
            select(IndexMedia.playback_position).where(IndexMedia.post_id == POST_ID)
        ).all()
    assert positions
    assert all(position is None for position in positions)


def test_mark_uses_future_content_watermark_without_rewriting_content(
    library: ReadLibrary,
) -> None:
    future = NOW + timedelta(days=3)
    library.record.media[AUDIO_ID].added_at = future
    library.store.save_post(library.folder, library.record)
    path = library.root / library.folder / 'post.json'
    before = path.read_bytes(), path.stat().st_mtime_ns
    result = library.reader.set_seen('writer', POST_ID, seen=True)
    assert result is not None
    assert result.post.seen_at == future
    assert result.post.pieces_added_at == future
    assert (
        library.reader.list_posts(
            'writer', PostFilters(unseen_only=True, tag='lesson')
        ).total
        == 0
    )
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_same_prefix_replacement_cannot_receive_another_posts_marks(
    library: ReadLibrary,
) -> None:
    library.record.post.id = 'bbbbbbbb-replacement'
    folder = library.root / library.folder
    write_post_record(folder, library.record)
    (folder / 'viewer.json').unlink()
    with pytest.raises(LibraryWriteError):
        library.reader.set_seen('writer', POST_ID, seen=True)
    assert not (folder / 'viewer.json').exists()


@pytest.mark.parametrize(
    'error', [KeyError('bug'), IndexError('bug'), RuntimeError('bug')]
)
def test_programming_failures_are_not_reclassified(
    library: ReadLibrary, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    monkeypatch.setattr(LibraryIndex, 'update_marks', Mock(side_effect=error))
    with pytest.raises(type(error)) as failure:
        library.reader.set_favorite('writer', POST_ID, favorite=False)
    assert failure.value is error


@pytest.mark.parametrize('failed_first_update', [False, True])
def test_same_size_and_timestamp_do_not_hide_position_changes(
    library: ReadLibrary, monkeypatch: pytest.MonkeyPatch, *, failed_first_update: bool
) -> None:
    writer = mutations.write_atomically
    path = library.root / library.folder / 'viewer.json'
    original = path.stat()

    def write_with_unchanged_timestamp(target: Path, data: bytes) -> None:
        writer(target, data)
        utime(target, ns=(original.st_atime_ns, original.st_mtime_ns))

    monkeypatch.setattr(mutations, 'write_atomically', write_with_unchanged_timestamp)
    identity = MediaIdentity(POST_ID, AUDIO_ID)
    if failed_first_update:
        with monkeypatch.context() as failure:
            failure.setattr(
                LibraryIndex, 'update_marks', Mock(side_effect=OSError('index failed'))
            )
            with pytest.raises(LibraryWriteError):
                library.reader.set_position('writer', identity, 12, 90)
    result = library.reader.set_position('writer', identity, 12, 90)
    assert result is not None
    assert result.playback == PlaybackPosition(12)
    assert path.stat().st_mtime_ns == original.st_mtime_ns
    assert path.stat().st_size == original.st_size
    with LibraryIndex(library.root).connect() as connection:
        position = connection.scalar(
            select(IndexMedia.playback_position).where(
                IndexMedia.post_id == POST_ID, IndexMedia.media_id == AUDIO_ID
            )
        )
    assert position == 12
