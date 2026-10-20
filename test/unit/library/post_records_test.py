"""Post-folder lookup preserves full identity and never changes the library."""

from collections.abc import Iterator
from dataclasses import replace
from datetime import datetime, timezone
from errno import EACCES, ENOSYS, EPERM
from os import stat_result
from pathlib import Path

import pytest

from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.post_folder import compose_post_directory_name
from boosty_downloader.domain.stored_post import PostMetadata, PostSync, StoredPost
from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidPostRecordError,
    UnsupportedPostSchemaError,
)
from boosty_downloader.infrastructure.library.json_store import write_post_record
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
FOLDER = 'writer/2026-10-12 - Original (abcdefgh)'


@pytest.fixture
def record() -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            id='abcdefgh-first',
            author='writer',
            url='https://boosty.to/writer/posts/abcdefgh-first',
            title='Original',
            created_at=NOW,
            updated_at=NOW,
            tags=['lesson'],
        ),
        sync=PostSync(NOW, NOW),
    )


def _create_folder(root: Path, post: PostMetadata, *, collision: int = 0) -> Path:
    name = compose_post_directory_name(
        post.title, post.created_at, post.id, collision=collision
    )
    folder = root / post.author / name
    folder.mkdir(parents=True)
    return folder


def _seed_record(root: Path, record: StoredPost, *, collision: int = 0) -> Path:
    folder = _create_folder(root, record.post, collision=collision)
    write_post_record(folder, record)
    return folder


def _symlink(link: Path, target: Path, *, is_directory: bool = True) -> None:
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


def _set_author_order(
    monkeypatch: pytest.MonkeyPatch, author: Path, children: list[Path]
) -> None:
    real_iterdir = Path.iterdir

    def ordered_iterdir(path: Path) -> Iterator[Path]:
        if path == author:
            return iter(children)
        return real_iterdir(path)

    monkeypatch.setattr(Path, 'iterdir', ordered_iterdir)


def test_changed_title_keeps_the_observed_folder(tmp_path: Path, record: StoredPost):
    folder = _seed_record(tmp_path, record)
    record.post.title = 'Renamed a week later'
    write_post_record(folder, record)

    assert JsonPostRecords(tmp_path).find_post('writer', record.post.id) == LocatedPost(
        FOLDER, record
    )


def test_full_ids_distinguish_posts_with_a_shared_prefix(
    tmp_path: Path, record: StoredPost
):
    first = _seed_record(tmp_path, record)
    other = replace(record, post=replace(record.post, id='abcdefgh-FIRST'))
    second = _seed_record(tmp_path, other, collision=1)
    store = JsonPostRecords(tmp_path)

    assert store.find_post('writer', record.post.id) == LocatedPost(
        first.relative_to(tmp_path).as_posix(), record
    )
    assert store.find_post('writer', other.post.id) == LocatedPost(
        second.relative_to(tmp_path).as_posix(), other
    )
    assert store.find_post('writer', 'abcdefgh-third') is None


def test_same_id_in_different_authors_is_independent(
    tmp_path: Path, record: StoredPost
):
    _seed_record(tmp_path, record)
    other = replace(record, post=replace(record.post, author='other-writer'))
    other_folder = _seed_record(tmp_path, other)
    store = JsonPostRecords(tmp_path)

    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER, record)
    assert store.find_post('other-writer', record.post.id) == LocatedPost(
        other_folder.relative_to(tmp_path).as_posix(), other
    )


def test_record_for_another_author_is_not_adopted(tmp_path: Path, record: StoredPost):
    folder = _create_folder(tmp_path, record.post)
    foreign = replace(record, post=replace(record.post, author='other-writer'))
    write_post_record(folder, foreign)
    store = JsonPostRecords(tmp_path)

    assert store.find_post('writer', record.post.id) is None
    assert (
        store.choose_post_folder(record.post)
        == 'writer/2026-10-12 - Original [2] (abcdefgh)'
    )


def test_one_recordless_folder_can_recover_either_full_id_until_a_record_exists(
    tmp_path: Path, record: StoredPost
):
    folder = _create_folder(tmp_path, record.post)
    (folder / 'video.mp4').write_bytes(b'retained video')
    store = JsonPostRecords(tmp_path)

    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER)
    assert store.find_post('writer', 'abcdefgh-second') == LocatedPost(FOLDER)
    write_post_record(folder, record)
    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER, record)
    assert store.find_post('writer', 'abcdefgh-second') is None
    assert (folder / 'video.mp4').read_bytes() == b'retained video'


def test_exact_record_wins_over_multiple_recordless_candidates(
    tmp_path: Path, record: StoredPost
):
    _create_folder(tmp_path, record.post, collision=1)
    _seed_record(tmp_path, record)
    _create_folder(tmp_path, record.post, collision=2)

    assert JsonPostRecords(tmp_path).find_post('writer', record.post.id) == LocatedPost(
        FOLDER, record
    )


def test_duplicate_full_identities_report_both_paths(
    tmp_path: Path, record: StoredPost
):
    first = _seed_record(tmp_path, record)
    second = _seed_record(tmp_path, record, collision=1)

    with pytest.raises(AmbiguousPostFolderError) as raised:
        JsonPostRecords(tmp_path).find_post('writer', record.post.id)

    assert first.relative_to(tmp_path).as_posix() in str(raised.value)
    assert second.relative_to(tmp_path).as_posix() in str(raised.value)


def test_multiple_recordless_folders_report_both_paths(
    tmp_path: Path, record: StoredPost
):
    first = _create_folder(tmp_path, record.post)
    second = _create_folder(tmp_path, record.post, collision=1)

    with pytest.raises(AmbiguousPostFolderError) as raised:
        JsonPostRecords(tmp_path).find_post('writer', record.post.id)

    assert first.relative_to(tmp_path).as_posix() in str(raised.value)
    assert second.relative_to(tmp_path).as_posix() in str(raised.value)


@pytest.mark.parametrize(
    ('data', 'error_type'),
    [
        pytest.param(b'{', InvalidPostRecordError, id='corrupt'),
        pytest.param(
            b'{"schema_version": 2}', UnsupportedPostSchemaError, id='unsupported'
        ),
    ],
)
def test_later_invalid_candidate_is_not_hidden_by_an_exact_match(
    tmp_path: Path,
    record: StoredPost,
    monkeypatch: pytest.MonkeyPatch,
    data: bytes,
    error_type: type[InvalidPostRecordError],
):
    exact = _seed_record(tmp_path, record)
    invalid = _create_folder(tmp_path, record.post, collision=1)
    record_path = invalid / 'post.json'
    record_path.write_bytes(data)
    _set_author_order(monkeypatch, exact.parent, [exact, invalid])

    with pytest.raises(error_type) as raised:
        JsonPostRecords(tmp_path).find_post('writer', record.post.id)

    assert str(record_path) in str(raised.value)
    assert record_path.read_bytes() == data


def test_unreadable_candidate_propagates_even_after_an_exact_match(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    exact = _seed_record(tmp_path, record)
    unreadable = _create_folder(tmp_path, record.post, collision=1) / 'post.json'
    error = PermissionError('candidate cannot be read')
    real_read_bytes = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == unreadable:
            raise error
        return real_read_bytes(path)

    _set_author_order(monkeypatch, exact.parent, [exact, unreadable.parent])
    monkeypatch.setattr(Path, 'read_bytes', read_bytes)
    with pytest.raises(PermissionError) as raised:
        JsonPostRecords(tmp_path).find_post('writer', record.post.id)
    assert raised.value is error


def test_each_lookup_loads_an_independent_current_snapshot(
    tmp_path: Path, record: StoredPost
):
    folder = _seed_record(tmp_path, record)
    store = JsonPostRecords(tmp_path)
    first = store.find_post('writer', record.post.id)
    second = store.find_post('writer', record.post.id)
    assert first is not None
    assert first.record is not None
    first.record.post.tags.append('only in memory')

    assert second == LocatedPost(FOLDER, record)
    record.post.title = 'Published update'
    write_post_record(folder, record)
    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER, record)
    assert second != LocatedPost(FOLDER, record)


def test_successful_enumeration_occurs_once_per_author(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    _seed_record(tmp_path, record)
    other = replace(record, post=replace(record.post, author='other-writer'))
    _seed_record(tmp_path, other)
    real_iterdir = Path.iterdir
    visits: list[Path] = []

    def count_iterdir(path: Path) -> Iterator[Path]:
        visits.append(path)
        return real_iterdir(path)

    monkeypatch.setattr(Path, 'iterdir', count_iterdir)
    store = JsonPostRecords(tmp_path)
    for _ in range(2):
        assert store.find_post('writer', record.post.id) is not None
        assert store.find_post('writer', 'unseen') is None
        assert store.find_post('other-writer', other.post.id) is not None
    assert visits.count(tmp_path / 'writer') == 1
    assert visits.count(tmp_path / 'other-writer') == 1


def test_failed_partial_enumeration_is_retried_in_full(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    first = _seed_record(tmp_path, record)
    other = replace(record, post=replace(record.post, id='ijklmnop-other'))
    second = _seed_record(tmp_path, other)
    real_iterdir = Path.iterdir
    error = PermissionError('author enumeration interrupted')
    failed = False

    def fail_once(path: Path) -> Iterator[Path]:
        nonlocal failed
        if path == first.parent and not failed:
            failed = True
            yield first
            raise error
        yield from real_iterdir(path)

    monkeypatch.setattr(Path, 'iterdir', fail_once)
    store = JsonPostRecords(tmp_path)
    with pytest.raises(PermissionError) as raised:
        store.find_post('writer', record.post.id)
    assert raised.value is error
    assert store.find_post('writer', other.post.id) == LocatedPost(
        second.relative_to(tmp_path).as_posix(), other
    )


def test_deleted_folder_is_missing_but_deleted_record_leaves_recoverable_folder(
    tmp_path: Path, record: StoredPost
):
    folder = _seed_record(tmp_path, record)
    store = JsonPostRecords(tmp_path)
    assert store.find_post('writer', record.post.id) is not None
    (folder / 'post.json').unlink()

    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER)
    folder.rmdir()
    assert store.find_post('writer', record.post.id) is None


def test_disappearance_during_record_read_does_not_return_a_missing_folder(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    folder = _create_folder(tmp_path, record.post)
    real_read_bytes = Path.read_bytes

    def remove_folder(path: Path) -> bytes:
        if path == folder / 'post.json':
            folder.rmdir()
        return real_read_bytes(path)

    monkeypatch.setattr(Path, 'read_bytes', remove_folder)
    assert JsonPostRecords(tmp_path).find_post('writer', record.post.id) is None


def test_lookup_ignores_files_unrecognized_folders_nested_posts_and_other_prefixes(
    tmp_path: Path, record: StoredPost
):
    folder = tmp_path / FOLDER
    folder.parent.mkdir()
    folder.write_bytes(b'ordinary file')
    unrecognized = folder.parent / 'personal-notes'
    unrecognized.mkdir()
    (unrecognized / 'post.json').write_bytes(b'{')
    nested = unrecognized / folder.name
    nested.mkdir()
    write_post_record(nested, record)
    unrelated = _create_folder(tmp_path, replace(record.post, id='ijklmnop-other'))
    (unrelated / 'post.json').write_bytes(b'{')

    assert JsonPostRecords(tmp_path).find_post('writer', record.post.id) is None


def test_read_and_choice_preserve_files_and_modification_times(
    tmp_path: Path, record: StoredPost
):
    folder = _seed_record(tmp_path, record)
    (folder / 'video.mp4').write_bytes(b'media')
    (folder / 'viewer.json').write_bytes(b'viewing marks')
    files = {path: path.read_bytes() for path in folder.iterdir()}
    modified = {path: path.stat().st_mtime_ns for path in files}
    entries = set(tmp_path.rglob('*'))
    store = JsonPostRecords(tmp_path)

    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER, record)
    store.choose_post_folder(record.post)

    assert set(tmp_path.rglob('*')) == entries
    assert {path: path.read_bytes() for path in files} == files
    assert {path: path.stat().st_mtime_ns for path in files} == modified


@pytest.mark.parametrize(
    'root_exists', [False, True], ids=['missing-root', 'missing-author']
)
def test_missing_library_choice_creates_and_reserves_nothing(
    tmp_path: Path, record: StoredPost, *, root_exists: bool
):
    root = tmp_path / 'library'
    if root_exists:
        root.mkdir()
    store = JsonPostRecords(root)
    other = replace(record.post, id='abcdefgh-second')

    assert store.find_post('writer', record.post.id) is None
    assert store.choose_post_folder(record.post) == FOLDER
    assert store.choose_post_folder(other) == FOLDER
    assert store.choose_post_folder(record.post) == FOLDER
    assert store.find_post('writer', record.post.id) is None
    assert store.find_post('writer', other.id) is None
    assert root.exists() is root_exists
    assert not (root / 'writer').exists()


def test_choice_skips_occupied_files_and_directories(
    tmp_path: Path, record: StoredPost
):
    ordinary = tmp_path / FOLDER
    ordinary.parent.mkdir()
    ordinary.write_bytes(b'do not overwrite')
    occupied = _create_folder(tmp_path, record.post, collision=1)
    store = JsonPostRecords(tmp_path)

    assert (
        store.choose_post_folder(record.post)
        == 'writer/2026-10-12 - Original [3] (abcdefgh)'
    )
    assert ordinary.read_bytes() == b'do not overwrite'
    assert list(occupied.iterdir()) == []


def test_choice_rechecks_disk_after_an_earlier_suggestion(
    tmp_path: Path, record: StoredPost
):
    store = JsonPostRecords(tmp_path)
    assert store.choose_post_folder(record.post) == FOLDER
    _create_folder(tmp_path, record.post)

    assert (
        store.choose_post_folder(record.post)
        == 'writer/2026-10-12 - Original [2] (abcdefgh)'
    )


def test_choice_treats_a_dangling_symlink_as_occupied(
    tmp_path: Path, record: StoredPost
):
    link = tmp_path / FOLDER
    link.parent.mkdir()
    _symlink(link, tmp_path / 'missing')

    assert (
        JsonPostRecords(tmp_path).choose_post_folder(record.post)
        == 'writer/2026-10-12 - Original [2] (abcdefgh)'
    )
    assert link.is_symlink()


@pytest.mark.parametrize(
    'author',
    [
        '',
        '.',
        '..',
        '../writer',
        'writer/child',
        r'writer\child',
        'writer.',
        'writer ',
        'CON',
        'wri:ter',
        'writer\n',
    ],
)
def test_lookup_and_choice_reject_nonportable_author_components(
    tmp_path: Path, record: StoredPost, author: str
):
    store = JsonPostRecords(tmp_path)

    with pytest.raises(ValueError, match=r'[Aa]uthor'):
        store.find_post(author, record.post.id)
    with pytest.raises(ValueError, match=r'[Aa]uthor'):
        store.choose_post_folder(replace(record.post, author=author))
    assert list(tmp_path.iterdir()) == []


def test_lookup_and_choice_reject_an_author_link_outside_the_library(
    tmp_path: Path, record: StoredPost
):
    root = tmp_path / 'library'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    _symlink(root / 'writer', outside)
    store = JsonPostRecords(root)

    with pytest.raises(ValueError, match=r'[Rr]oot|[Ll]ibrary|[Oo]utside'):
        store.find_post('writer', record.post.id)
    with pytest.raises(ValueError, match=r'[Rr]oot|[Ll]ibrary|[Oo]utside'):
        store.choose_post_folder(record.post)
    assert list(outside.iterdir()) == []


def test_lookup_rejects_a_post_folder_link_outside_the_library(
    tmp_path: Path, record: StoredPost
):
    root = tmp_path / 'library'
    (root / 'writer').mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    _symlink(root / FOLDER, outside)

    with pytest.raises(ValueError, match=r'[Rr]oot|[Ll]ibrary|[Oo]utside'):
        JsonPostRecords(root).find_post('writer', record.post.id)
    assert list(outside.iterdir()) == []


def test_cached_post_folder_is_checked_again_after_replacement_by_an_outside_link(
    tmp_path: Path, record: StoredPost
):
    root = tmp_path / 'library'
    folder = _create_folder(root, record.post)
    outside = tmp_path / 'outside'
    outside.mkdir()
    store = JsonPostRecords(root)
    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER)
    folder.rmdir()
    _symlink(folder, outside)

    with pytest.raises(ValueError, match=r'[Rr]oot|[Ll]ibrary|[Oo]utside'):
        store.find_post('writer', record.post.id)
    assert list(outside.iterdir()) == []


def test_lookup_rejects_a_record_file_link_outside_the_library(
    tmp_path: Path, record: StoredPost
):
    root = tmp_path / 'library'
    folder = _create_folder(root, record.post)
    outside = tmp_path / 'outside'
    outside.mkdir()
    write_post_record(outside, record)
    _symlink(folder / 'post.json', outside / 'post.json', is_directory=False)

    with pytest.raises(ValueError, match=r'[Rr]oot|[Ll]ibrary|[Oo]utside'):
        JsonPostRecords(root).find_post('writer', record.post.id)


def test_unreadable_indexed_folder_is_not_reported_as_missing(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    folder = _create_folder(tmp_path, record.post)
    store = JsonPostRecords(tmp_path)
    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER)
    real_stat = Path.stat
    error = PermissionError('folder cannot be inspected')

    def stat(path: Path, *, follow_symlinks: bool = True) -> stat_result:
        if path == folder:
            raise error
        return real_stat(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, 'stat', stat)
    with pytest.raises(PermissionError) as raised:
        store.find_post('writer', record.post.id)
    assert raised.value is error


def test_file_in_place_of_author_directory_propagates_filesystem_error(
    tmp_path: Path, record: StoredPost
):
    author = tmp_path / 'writer'
    author.write_bytes(b'not a directory')

    with pytest.raises((NotADirectoryError, PermissionError)):
        JsonPostRecords(tmp_path).find_post('writer', record.post.id)
    assert author.read_bytes() == b'not a directory'


def test_choice_skips_a_post_link_outside_the_library(
    tmp_path: Path, record: StoredPost
):
    root = tmp_path / 'library'
    (root / 'writer').mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    _symlink(root / FOLDER, outside)

    assert JsonPostRecords(root).choose_post_folder(record.post) == (
        'writer/2026-10-12 - Original [2] (abcdefgh)'
    )
    assert list(outside.iterdir()) == []


def test_portable_unicode_author_identity_is_preserved(
    tmp_path: Path, record: StoredPost
):
    record.post.author = 'Автор'
    folder = _seed_record(tmp_path, record)
    store = JsonPostRecords(tmp_path)

    assert store.find_post(record.post.author, record.post.id) == LocatedPost(
        folder.relative_to(tmp_path).as_posix(), record
    )
    assert (
        store.choose_post_folder(record.post)
        == 'Автор/2026-10-12 - Original [2] (abcdefgh)'
    )


def test_choice_propagates_an_occupied_path_check_error_without_writes(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    store = JsonPostRecords(tmp_path)
    candidate = tmp_path / FOLDER
    real_lstat = Path.lstat
    error = PermissionError('candidate cannot be inspected')

    def lstat(path: Path) -> stat_result:
        if path == candidate:
            raise error
        return real_lstat(path)

    monkeypatch.setattr(Path, 'lstat', lstat)
    with pytest.raises(PermissionError) as raised:
        store.choose_post_folder(record.post)

    assert raised.value is error
    assert list(tmp_path.iterdir()) == []
