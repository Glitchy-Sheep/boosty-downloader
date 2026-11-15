"""Viewing marks belong to confirmed posts and survive failed filesystem writes."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from enum import Enum
from errno import EACCES, ENOSYS, EPERM
from pathlib import Path
from shutil import copytree, rmtree

import pytest

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.stored_post import (
    LockedPost,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library import post_marks
from boosty_downloader.infrastructure.library._viewer_json import encode_viewer_record
from boosty_downloader.infrastructure.library.author_records import save_locked_post
from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidAuthorRecordError,
    InvalidPostRecordError,
    InvalidViewerRecordError,
    UnsupportedViewerSchemaError,
)
from boosty_downloader.infrastructure.library.json_store import write_post_record
from boosty_downloader.infrastructure.library.post_marks import (
    VIEWER_RECORD_FILENAME,
    JsonPostMarks,
)
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
POST_ID = '00000000-0000-4000-8000-000000000001'
SECOND_ID = '00000000-0000-4000-8000-000000000002'
MEDIA_ID = 'audio:lesson'


class Operation(Enum):
    read = 'read'
    save = 'save'


class BadRecord(Enum):
    corrupt = 'corrupt'
    unsupported = 'unsupported'
    foreign_author = 'foreign_author'
    foreign_post = 'foreign_post'


class LinkLocation(Enum):
    author = 'author'
    post = 'post'
    viewer = 'viewer'
    missing_viewer = 'missing_viewer'


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'library'


@pytest.fixture
def record() -> StoredPost:
    return StoredPost(
        PostMetadata(POST_ID, 'writer', '', 'Lesson', NOW, NOW),
        PostSync(NOW, NOW),
    )


@pytest.fixture
def folder(root: Path, record: StoredPost) -> Path:
    return _save_post(root, record)


@pytest.fixture
def marks() -> PostMarks:
    return PostMarks(
        seen_at=NOW, favorite=True, positions={MEDIA_ID: PlaybackPosition(42.5, NOW)}
    )


def _save_post(root: Path, record: StoredPost) -> Path:
    records = JsonPostRecords(root)
    folder = records.choose_post_folder(record.post)
    records.save_post(folder, record)
    return root / folder


def _run(operation: Operation, store: JsonPostMarks) -> PostMarks | None:
    match operation:
        case Operation.read:
            return store.get_marks('writer', POST_ID)
        case Operation.save:
            store.save_marks('writer', POST_ID, PostMarks(favorite=True))
            return None


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob('*')
        if path.is_file()
    }


def _symlink(link: Path, target: Path, *, is_directory: bool) -> None:
    try:
        link.symlink_to(target, target_is_directory=is_directory)
    except NotImplementedError:
        pytest.skip('Filesystem does not support symlinks')
    except OSError as error:
        if (
            error.errno in {EPERM, EACCES, ENOSYS}
            or getattr(error, 'winerror', None) == 1314
        ):
            pytest.skip('Filesystem does not permit symlinks')
        raise


def _bad_bytes(problem: BadRecord) -> bytes:
    match problem:
        case BadRecord.corrupt:
            return b'{broken'
        case BadRecord.unsupported:
            return b'{"schema_version": 2}'
        case BadRecord.foreign_author:
            return encode_viewer_record('other', POST_ID, PostMarks())
        case BadRecord.foreign_post:
            return encode_viewer_record('writer', SECOND_ID, PostMarks())


def test_unknown_post_does_not_create_a_library(root: Path) -> None:
    store = JsonPostMarks(root)

    assert store.get_marks('writer', POST_ID) is None
    with pytest.raises(LookupError):
        store.save_marks('writer', POST_ID, PostMarks())
    assert not root.exists()


def test_known_post_has_independent_empty_marks_without_writes(
    root: Path, folder: Path
) -> None:
    store = JsonPostMarks(root)
    before = _snapshot(root)
    first = store.get_marks('writer', POST_ID)
    assert first == PostMarks()
    assert first is not None
    first.positions[MEDIA_ID] = PlaybackPosition(10)

    assert store.get_marks('writer', POST_ID) == PostMarks()
    assert _snapshot(root) == before
    assert not (folder / VIEWER_RECORD_FILENAME).exists()


def test_locked_only_post_is_known_but_cannot_save_marks(
    root: Path, record: StoredPost
) -> None:
    save_locked_post(root, LockedPost(record.post, NOW))
    store = JsonPostMarks(root)
    before = _snapshot(root)
    tree = set(root.rglob('*'))

    assert store.get_marks('writer', POST_ID) == PostMarks()
    assert store.get_marks('writer', SECOND_ID) is None
    with pytest.raises(LookupError):
        store.save_marks('writer', POST_ID, PostMarks(favorite=True))
    assert _snapshot(root) == before
    assert set(root.rglob('*')) == tree


def test_saved_marks_are_independent_snapshots(
    root: Path, folder: Path, marks: PostMarks
) -> None:
    expected = deepcopy(marks)
    store = JsonPostMarks(root)
    store.save_marks('writer', POST_ID, marks)
    marks.positions[MEDIA_ID].seconds = 99
    marks.favorite = False
    first = store.get_marks('writer', POST_ID)
    second = store.get_marks('writer', POST_ID)
    assert first == second == expected
    assert first is not None
    first.positions[MEDIA_ID].finished_at = None
    first.positions.clear()

    assert second == expected
    assert JsonPostMarks(root).get_marks('writer', POST_ID) == expected
    assert (folder / VIEWER_RECORD_FILENAME).is_file()


def test_reads_external_changes_and_saves_complete_replacements(
    root: Path, folder: Path, record: StoredPost, marks: PostMarks
) -> None:
    store = JsonPostMarks(root)
    store.save_marks('writer', POST_ID, PostMarks())
    (folder / VIEWER_RECORD_FILENAME).write_bytes(
        encode_viewer_record('writer', POST_ID, marks)
    )
    save_locked_post(root, LockedPost(record.post, NOW))

    assert store.get_marks('writer', POST_ID) == marks
    store.save_marks('writer', POST_ID, PostMarks())
    assert store.get_marks('writer', POST_ID) == PostMarks()


def test_full_post_identity_and_author_keep_marks_separate(
    root: Path, record: StoredPost, folder: Path, marks: PostMarks
) -> None:
    second = replace(record, post=replace(record.post, id=SECOND_ID))
    other = replace(record, post=replace(record.post, author='other'))
    _save_post(root, second)
    _save_post(root, other)
    store = JsonPostMarks(root)

    store.save_marks('writer', POST_ID, marks)
    store.save_marks('writer', SECOND_ID, PostMarks(seen_at=NOW))
    store.save_marks('other', POST_ID, PostMarks(favorite=True))

    assert store.get_marks('writer', POST_ID) == marks
    assert store.get_marks('writer', SECOND_ID) == PostMarks(seen_at=NOW)
    assert store.get_marks('other', POST_ID) == PostMarks(favorite=True)
    assert (folder / VIEWER_RECORD_FILENAME).is_file()


@pytest.mark.parametrize('is_locked', [False, True])
def test_recordless_folder_retains_marks_until_identity_is_restored(
    root: Path, record: StoredPost, folder: Path, marks: PostMarks, *, is_locked: bool
) -> None:
    store = JsonPostMarks(root)
    store.save_marks('writer', POST_ID, marks)
    (folder / 'post.json').unlink()
    if is_locked:
        save_locked_post(root, LockedPost(record.post, NOW))
    before = _snapshot(root)

    if is_locked:
        assert store.get_marks('writer', POST_ID) == PostMarks()
    else:
        assert store.get_marks('writer', POST_ID) is None
    with pytest.raises(LookupError):
        store.save_marks('writer', POST_ID, PostMarks())
    assert _snapshot(root) == before
    write_post_record(folder, record)
    assert store.get_marks('writer', POST_ID) == marks


def test_same_instance_discovers_new_and_renamed_post_folders(
    root: Path, record: StoredPost, marks: PostMarks
) -> None:
    store = JsonPostMarks(root)
    assert store.get_marks('writer', POST_ID) is None
    folder = _save_post(root, record)
    store.save_marks('writer', POST_ID, marks)
    renamed = folder.with_name(folder.name.replace('Lesson', 'Renamed'))
    folder.rename(renamed)

    assert store.get_marks('writer', POST_ID) == marks
    store.save_marks('writer', POST_ID, PostMarks())
    assert not folder.exists()
    assert JsonPostMarks(root).get_marks('writer', POST_ID) == PostMarks()


def test_root_stays_fixed_after_working_directory_changes(
    tmp_path: Path, root: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    store = JsonPostMarks(Path(root.name))
    monkeypatch.chdir(folder)

    store.save_marks('writer', POST_ID, PostMarks(favorite=True))

    assert store.get_marks('writer', POST_ID) == PostMarks(favorite=True)
    assert not (folder / root.name).exists()


@pytest.mark.parametrize('operation', list(Operation))
@pytest.mark.parametrize('problem', list(BadRecord))
def test_invalid_existing_marks_are_not_reset(
    root: Path, folder: Path, operation: Operation, problem: BadRecord
) -> None:
    path = folder / VIEWER_RECORD_FILENAME
    path.write_bytes(_bad_bytes(problem))
    before = _snapshot(root)
    expected: type[InvalidViewerRecordError] = InvalidViewerRecordError
    if problem is BadRecord.unsupported:
        expected = UnsupportedViewerSchemaError

    with pytest.raises(expected) as raised:
        _run(operation, JsonPostMarks(root))

    assert str(path) in str(raised.value)
    assert _snapshot(root) == before


@pytest.mark.parametrize('has_marks', [False, True])
def test_invalid_input_does_not_change_saved_files(
    root: Path, folder: Path, marks: PostMarks, *, has_marks: bool
) -> None:
    store = JsonPostMarks(root)
    if has_marks:
        store.save_marks('writer', POST_ID, marks)
    before = _snapshot(root)
    marks.positions[MEDIA_ID].seconds = -1

    with pytest.raises(InvalidViewerRecordError) as raised:
        store.save_marks('writer', POST_ID, marks)

    assert str(folder / VIEWER_RECORD_FILENAME) in str(raised.value)
    assert _snapshot(root) == before


@pytest.mark.parametrize('operation', list(Operation))
def test_corrupt_post_identity_is_not_treated_as_missing(
    root: Path, folder: Path, operation: Operation
) -> None:
    (folder / 'post.json').write_bytes(b'{broken')
    with pytest.raises(InvalidPostRecordError):
        _run(operation, JsonPostMarks(root))
    assert not (folder / VIEWER_RECORD_FILENAME).exists()


@pytest.mark.parametrize('operation', list(Operation))
def test_ambiguous_post_folders_are_not_guessed(
    root: Path, folder: Path, operation: Operation
) -> None:
    copytree(folder, folder.with_name(folder.name.replace('Lesson', 'Duplicate')))
    before = _snapshot(root)
    with pytest.raises(AmbiguousPostFolderError):
        _run(operation, JsonPostMarks(root))
    assert _snapshot(root) == before


@pytest.mark.parametrize('operation', list(Operation))
@pytest.mark.parametrize('location', list(LinkLocation))
def test_escaping_links_are_rechecked_after_an_earlier_lookup(
    tmp_path: Path,
    root: Path,
    folder: Path,
    operation: Operation,
    location: LinkLocation,
) -> None:
    store = JsonPostMarks(root)
    assert store.get_marks('writer', POST_ID) == PostMarks()
    outside = tmp_path / 'outside'
    outside.mkdir()
    match location:
        case LinkLocation.author:
            link = root / 'writer'
            target = link.rename(outside / 'writer')
        case LinkLocation.post:
            link = folder
            target = folder.rename(outside / 'post')
        case LinkLocation.viewer | LinkLocation.missing_viewer:
            link = folder / VIEWER_RECORD_FILENAME
            target = outside / VIEWER_RECORD_FILENAME
            if location is LinkLocation.viewer:
                target.write_bytes(encode_viewer_record('writer', POST_ID, PostMarks()))
    _symlink(
        link, target, is_directory=location in {LinkLocation.author, LinkLocation.post}
    )
    before = _snapshot(outside)

    with pytest.raises(ValueError, match='escapes the library root'):
        _run(operation, store)
    assert _snapshot(outside) == before


@pytest.mark.parametrize('operation', list(Operation))
def test_permission_errors_are_not_empty_marks(
    root: Path, folder: Path, operation: Operation, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = folder / VIEWER_RECORD_FILENAME
    original = Path.read_bytes

    def denied_read(candidate: Path) -> bytes:
        if candidate == path:
            raise PermissionError(EACCES, 'Marks cannot be read', str(candidate))
        return original(candidate)

    monkeypatch.setattr(Path, 'read_bytes', denied_read)
    with pytest.raises(PermissionError):
        _run(operation, JsonPostMarks(root))
    assert not path.exists()


def test_failed_atomic_replace_retains_old_marks_and_cleans_temporary_file(
    root: Path, folder: Path, marks: PostMarks, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = JsonPostMarks(root)
    store.save_marks('writer', POST_ID, marks)
    before = _snapshot(root)

    def fail_replace(source: Path, target: Path) -> Path:
        assert source.parent == folder
        assert target == folder / VIEWER_RECORD_FILENAME
        message = 'Cannot replace marks'
        raise PermissionError(message)

    monkeypatch.setattr(Path, 'replace', fail_replace)
    with pytest.raises(PermissionError):
        store.save_marks('writer', POST_ID, PostMarks())
    assert _snapshot(root) == before
    assert store.get_marks('writer', POST_ID) == marks


def test_deleted_folder_is_not_recreated_during_publication(
    root: Path, folder: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def encode_after_deletion(author: str, post_id: str, marks: PostMarks) -> bytes:
        data = encode_viewer_record(author, post_id, marks)
        rmtree(folder)
        return data

    monkeypatch.setattr(post_marks, 'encode_viewer_record', encode_after_deletion)
    store = JsonPostMarks(root)
    with pytest.raises(FileNotFoundError):
        store.save_marks('writer', POST_ID, PostMarks())
    assert not folder.exists()
    assert store.get_marks('writer', POST_ID) is None
    with pytest.raises(LookupError):
        store.save_marks('writer', POST_ID, PostMarks())
    assert not folder.exists()


def test_corrupt_locked_observation_cannot_establish_a_known_post(
    root: Path, record: StoredPost
) -> None:
    save_locked_post(root, LockedPost(record.post, NOW))
    path = root / 'writer/.boosty-downloader/locked.json'
    path.write_bytes(b'{broken')
    store = JsonPostMarks(root)

    with pytest.raises(InvalidAuthorRecordError):
        store.get_marks('writer', POST_ID)
    with pytest.raises(LookupError):
        store.save_marks('writer', POST_ID, PostMarks())
    assert path.read_bytes() == b'{broken'


@pytest.mark.parametrize('operation', list(Operation))
def test_directory_at_marks_path_is_not_treated_as_missing(
    root: Path, folder: Path, operation: Operation
) -> None:
    path = folder / VIEWER_RECORD_FILENAME
    path.mkdir()
    with pytest.raises((IsADirectoryError, PermissionError)):
        _run(operation, JsonPostMarks(root))
    assert path.is_dir()
