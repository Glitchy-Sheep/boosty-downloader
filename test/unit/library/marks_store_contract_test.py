"""Shared user-mark persistence contracts for JSON and the primary database."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from shutil import rmtree
from typing import TYPE_CHECKING, TypeAlias

import pytest
from support.synthetic_post import POST_ID

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LockedPost,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library.db_post_marks import DatabasePostMarks
from boosty_downloader.infrastructure.library.db_post_store import DatabasePostStore
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase
from boosty_downloader.infrastructure.library.errors import InvalidViewerRecordError
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from boosty_downloader.application.ports import PostStore

NOW = datetime(2026, 11, 15, 12, 34, 56, 123456, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=7)
SECOND_ID = '00000000-0000-4000-8000-000000000002'
MEDIA_ID = 'audio:lesson'
FUTURE_ID = 'future:retained'
EXTERNAL_ID = 'external_video:https://video.example/watch?v=fixture&list=course'
MarkAdapter: TypeAlias = JsonPostMarks | DatabasePostMarks


@dataclass(frozen=True, slots=True)
class LibraryCase:
    root: Path
    posts: PostStore
    marks: MarkAdapter


@dataclass(frozen=True, slots=True)
class FileSnapshot:
    content: bytes
    modified_ns: int


@dataclass(frozen=True, slots=True)
class LibrarySnapshot:
    paths: frozenset[str]
    files: dict[str, FileSnapshot]


@pytest.fixture(params=['json', 'database'])
def library(
    request: pytest.FixtureRequest, tmp_path: Path
) -> Generator[LibraryCase, None, None]:
    root = tmp_path / 'library'
    if request.param == 'json':
        yield LibraryCase(root, JsonPostStore(root), JsonPostMarks(root))
        return
    with LibraryDatabase.create(tmp_path / 'library.db') as database:
        yield LibraryCase(
            root, DatabasePostStore(root, database), DatabasePostMarks(root, database)
        )


@pytest.fixture
def record() -> StoredPost:
    return StoredPost(
        PostMetadata(
            POST_ID, 'writer', 'https://boosty.to/example', 'Lesson', NOW, NOW
        ),
        PostSync(NOW, NOW),
    )


@pytest.fixture
def marks() -> PostMarks:
    return PostMarks(
        seen_at=NOW,
        favorite=True,
        positions={
            MEDIA_ID: PlaybackPosition(42.5, NOW),
            FUTURE_ID: PlaybackPosition(12),
            EXTERNAL_ID: PlaybackPosition(81.125, LATER),
        },
    )


def _save_post(library: LibraryCase, record: StoredPost) -> str:
    folder = library.posts.choose_post_folder(record.post)
    library.posts.save_post(folder, record)
    return folder


def _snapshot(root: Path) -> LibrarySnapshot:
    paths = list(root.rglob('*'))
    return LibrarySnapshot(
        frozenset(path.relative_to(root).as_posix() for path in paths),
        {
            path.relative_to(root).as_posix(): FileSnapshot(
                path.read_bytes(), path.stat().st_mtime_ns
            )
            for path in paths
            if path.is_file()
        },
    )


def test_unknown_post_reads_and_rejected_saves_create_no_library(
    library: LibraryCase,
):
    assert library.marks.get_marks('writer', POST_ID) is None
    with pytest.raises(LookupError):
        library.marks.save_marks('writer', POST_ID, PostMarks())
    assert not library.root.exists()


def test_unowned_recordless_folder_does_not_confirm_a_post(
    library: LibraryCase,
    record: StoredPost,
):
    folder = library.posts.choose_post_folder(record.post)
    target = library.root / folder
    target.mkdir(parents=True)
    (target / 'notes.txt').write_bytes(b'User notes')
    before = _snapshot(library.root)

    assert library.marks.get_marks('writer', POST_ID) is None
    with pytest.raises(LookupError):
        library.marks.save_marks('writer', POST_ID, PostMarks(favorite=True))
    assert _snapshot(library.root) == before


def test_saved_post_defaults_are_independent_and_read_without_writes(
    library: LibraryCase,
    record: StoredPost,
):
    _save_post(library, record)
    before = _snapshot(library.root)
    first = library.marks.get_marks('writer', POST_ID)
    assert first == PostMarks()
    assert first is not None
    first.positions[FUTURE_ID] = PlaybackPosition(10)
    first.favorite = True

    assert library.marks.get_marks('writer', POST_ID) == PostMarks()
    assert _snapshot(library.root) == before


def test_inputs_and_each_read_own_their_nested_mark_values(
    library: LibraryCase,
    record: StoredPost,
    marks: PostMarks,
):
    _save_post(library, record)
    expected = deepcopy(marks)
    library.marks.save_marks('writer', POST_ID, marks)
    marks.favorite = False
    marks.positions[MEDIA_ID].seconds = 999
    marks.positions.pop(EXTERNAL_ID)
    first = library.marks.get_marks('writer', POST_ID)
    second = library.marks.get_marks('writer', POST_ID)
    assert first == second == expected
    assert first is not None
    first.positions[MEDIA_ID].finished_at = None
    first.positions.clear()
    first.seen_at = None

    assert second == expected
    assert library.marks.get_marks('writer', POST_ID) == expected


def test_save_replaces_scalars_and_positions_including_unknown_media_ids(
    library: LibraryCase,
    record: StoredPost,
    marks: PostMarks,
):
    _save_post(library, record)
    assert record.media == {}
    library.marks.save_marks('writer', POST_ID, marks)
    assert library.marks.get_marks('writer', POST_ID) == marks
    replacement = PostMarks(positions={FUTURE_ID: PlaybackPosition(0)})
    library.marks.save_marks('writer', POST_ID, replacement)

    assert library.marks.get_marks('writer', POST_ID) == replacement
    library.marks.save_marks('writer', POST_ID, PostMarks())
    assert library.marks.get_marks('writer', POST_ID) == PostMarks()


def test_playback_completion_does_not_compute_seen_favorite_or_other_times(
    library: LibraryCase,
    record: StoredPost,
):
    _save_post(library, record)
    finished = PostMarks(positions={MEDIA_ID: PlaybackPosition(0, NOW)})
    library.marks.save_marks('writer', POST_ID, finished)
    assert library.marks.get_marks('writer', POST_ID) == finished
    unfinished = PostMarks(
        seen_at=LATER, favorite=True, positions={MEDIA_ID: PlaybackPosition(3)}
    )
    library.marks.save_marks('writer', POST_ID, unfinished)
    assert library.marks.get_marks('writer', POST_ID) == unfinished


def test_all_clocks_normalize_to_utc_without_mutating_the_input(
    library: LibraryCase,
    record: StoredPost,
):
    _save_post(library, record)
    local_time = NOW.astimezone(timezone(timedelta(hours=3)))
    marks = PostMarks(
        seen_at=local_time, positions={FUTURE_ID: PlaybackPosition(7, local_time)}
    )
    original = deepcopy(marks)
    library.marks.save_marks('writer', POST_ID, marks)
    loaded = library.marks.get_marks('writer', POST_ID)

    assert loaded == marks
    assert loaded is not None
    assert loaded.seen_at is not None
    assert loaded.seen_at.tzinfo is timezone.utc
    finished_at = loaded.positions[FUTURE_ID].finished_at
    assert finished_at is not None
    assert finished_at.tzinfo is timezone.utc
    assert marks == original
    assert marks.seen_at is local_time


def test_author_and_full_post_identity_keep_marks_separate(
    library: LibraryCase,
    record: StoredPost,
    marks: PostMarks,
):
    _save_post(library, record)
    _save_post(library, replace(record, post=replace(record.post, id=SECOND_ID)))
    _save_post(library, replace(record, post=replace(record.post, author='another')))
    library.marks.save_marks('writer', POST_ID, marks)
    library.marks.save_marks('writer', SECOND_ID, PostMarks(seen_at=NOW))
    library.marks.save_marks('another', POST_ID, PostMarks(favorite=True))

    assert library.marks.get_marks('writer', POST_ID) == marks
    assert library.marks.get_marks('writer', SECOND_ID) == PostMarks(seen_at=NOW)
    assert library.marks.get_marks('another', POST_ID) == PostMarks(favorite=True)


def test_locked_saved_posts_can_replace_their_existing_marks(
    library: LibraryCase,
    record: StoredPost,
    marks: PostMarks,
):
    _save_post(library, record)
    library.marks.save_marks('writer', POST_ID, marks)
    locked = LockedPost(replace(record.post, title='Locked overview'), LATER)
    library.posts.save_locked_post(locked)

    assert library.marks.get_marks('writer', POST_ID) == marks
    replacement = PostMarks(positions={EXTERNAL_ID: PlaybackPosition(13)})
    library.marks.save_marks('writer', POST_ID, replacement)
    assert library.marks.get_marks('writer', POST_ID) == replacement
    assert library.posts.load_locked_post('writer', POST_ID) == locked


def test_locked_only_post_has_defaults_but_cannot_save_marks(
    library: LibraryCase,
    record: StoredPost,
):
    library.posts.save_locked_post(LockedPost(record.post, NOW))
    before = _snapshot(library.root)
    first = library.marks.get_marks('writer', POST_ID)
    assert first == PostMarks()
    assert first is not None
    first.favorite = True
    assert library.marks.get_marks('writer', POST_ID) == PostMarks()
    with pytest.raises(LookupError):
        library.marks.save_marks('writer', POST_ID, PostMarks(favorite=True))
    assert _snapshot(library.root) == before


@pytest.mark.parametrize('locked', [False, True])
def test_missing_saved_folder_hides_marks_and_is_never_recreated_by_marks(
    library: LibraryCase,
    record: StoredPost,
    marks: PostMarks,
    *,
    locked: bool,
):
    folder = _save_post(library, record)
    library.marks.save_marks('writer', POST_ID, marks)
    if locked:
        library.posts.save_locked_post(LockedPost(record.post, NOW))
    rmtree(library.root / folder)
    before = _snapshot(library.root)
    expected = PostMarks() if locked else None

    assert library.marks.get_marks('writer', POST_ID) == expected
    with pytest.raises(LookupError):
        library.marks.save_marks('writer', POST_ID, PostMarks())
    assert not (library.root / folder).exists()
    assert _snapshot(library.root) == before


def test_downloader_and_access_updates_preserve_all_user_marks(
    library: LibraryCase,
    record: StoredPost,
    marks: PostMarks,
):
    record.media[MEDIA_ID] = MediaEntry(
        MediaKind.audio,
        MediaStatus.downloaded,
        NOW,
        0,
        path='audio/lesson.mp3',
        size=12,
        removed_at=LATER,
    )
    folder = _save_post(library, record)
    library.marks.save_marks('writer', POST_ID, marks)
    record.post.title = 'Changed title'
    record.media.clear()
    library.posts.save_post(folder, record)
    library.posts.save_author(AuthorInfo('writer', LATER, title='Updated blog'))
    library.posts.save_locked_post(LockedPost(record.post, LATER))
    assert library.marks.get_marks('writer', POST_ID) == marks
    library.posts.clear_locked_post('writer', POST_ID)
    assert library.marks.get_marks('writer', POST_ID) == marks


@pytest.mark.parametrize(
    'invalid', ['negative', 'infinite', 'boolean-seconds', 'blank-id', 'naive']
)
def test_invalid_replacement_retains_the_previous_snapshot(
    library: LibraryCase,
    record: StoredPost,
    marks: PostMarks,
    invalid: str,
):
    _save_post(library, record)
    library.marks.save_marks('writer', POST_ID, marks)
    invalid_marks = deepcopy(marks)
    match invalid:
        case 'negative':
            invalid_marks.positions[MEDIA_ID].seconds = -1
        case 'infinite':
            invalid_marks.positions[MEDIA_ID].seconds = float('inf')
        case 'boolean-seconds':
            invalid_marks.positions[MEDIA_ID].seconds = True
        case 'blank-id':
            invalid_marks.positions[' '] = PlaybackPosition(1)
        case 'naive':
            invalid_marks.seen_at = NOW.replace(tzinfo=None)
        case _:
            pytest.fail(f'Unknown invalid snapshot: {invalid}')
    before = _snapshot(library.root)

    with pytest.raises(InvalidViewerRecordError):
        library.marks.save_marks('writer', POST_ID, invalid_marks)
    assert library.marks.get_marks('writer', POST_ID) == marks
    assert _snapshot(library.root) == before
