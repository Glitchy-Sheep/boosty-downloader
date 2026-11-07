"""Saving respects post ownership and records only folders that exist on disk."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from enum import Enum
from errno import EACCES, ENOSYS, EPERM
from os import stat_result
from pathlib import Path
from unittest.mock import Mock

import pytest

from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.stored_post import PostMetadata, PostSync, StoredPost
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError
from boosty_downloader.infrastructure.library.json_store import (
    read_post_record,
    write_post_record,
)
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
FOLDER = 'writer/2026-10-12 - Original (abcdefgh)'
ALTERNATIVE = 'writer/2026-10-12 - Original [2] (abcdefgh)'


class LinkLocation(Enum):
    author = 'author'
    post = 'post'
    record = 'record'


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


def _seed_record(root: Path, folder: str, record: StoredPost) -> Path:
    path = root / folder
    path.mkdir(parents=True, exist_ok=True)
    write_post_record(path, record)
    return path


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


def test_save_creates_and_indexes_a_record_after_an_empty_lookup(
    tmp_path: Path, record: StoredPost
):
    root = tmp_path / 'missing-library'
    store = JsonPostRecords(root)
    assert store.find_post('writer', record.post.id) is None
    original = deepcopy(record)

    store.save_post(store.choose_post_folder(record.post), record)

    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER, original)
    assert JsonPostRecords(root).find_post('writer', record.post.id) == LocatedPost(
        FOLDER, original
    )
    record.post.tags.append('not saved')
    assert read_post_record(root / FOLDER) == original
    assert {path.relative_to(root).as_posix() for path in root.rglob('*')} == {
        'writer',
        FOLDER,
        f'{FOLDER}/post.json',
    }


def test_title_update_keeps_the_folder_and_returns_independent_records(
    tmp_path: Path, record: StoredPost
):
    store = JsonPostRecords(tmp_path)
    store.save_post(FOLDER, record)
    original = store.find_post('writer', record.post.id)
    record.post.title = 'Renamed a week later'
    store.save_post(FOLDER, record)

    current = store.find_post('writer', record.post.id)
    assert current == LocatedPost(FOLDER, record)
    assert original is not None
    assert original.record is not None
    assert original.record.post.title == 'Original'
    assert current is not None
    assert current.record is not None
    current.record.post.tags.clear()
    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER, record)
    assert [path.name for path in (tmp_path / 'writer').iterdir()] == [
        Path(FOLDER).name
    ]


def test_existing_identity_cannot_move_to_another_valid_folder(
    tmp_path: Path, record: StoredPost
):
    folder = _seed_record(tmp_path, FOLDER, record)
    before = (folder / 'post.json').read_bytes()

    with pytest.raises(ValueError, match=r'[Ff]older|[Aa]lready|[Mm]ove'):
        JsonPostRecords(tmp_path).save_post(ALTERNATIVE, record)

    assert (folder / 'post.json').read_bytes() == before
    assert not (tmp_path / ALTERNATIVE).exists()


@pytest.mark.parametrize('foreign_author', ['writer', 'another-writer'])
def test_choice_is_not_a_reservation_and_save_rechecks_target_ownership(
    tmp_path: Path, record: StoredPost, foreign_author: str
):
    store = JsonPostRecords(tmp_path)
    assert store.find_post('writer', record.post.id) is None
    choice = store.choose_post_folder(record.post)
    foreign = replace(
        record, post=replace(record.post, id='abcdefgh-second', author=foreign_author)
    )
    target = _seed_record(tmp_path, choice, foreign)
    before = (target / 'post.json').read_bytes()

    with pytest.raises(ValueError, match=r'[Ii]dentity|[Oo]wn|[Aa]nother|[Dd]ifferent'):
        store.save_post(choice, record)

    assert (target / 'post.json').read_bytes() == before
    assert store.choose_post_folder(record.post) == ALTERNATIVE


def test_save_sees_an_identity_published_in_an_already_indexed_folder(
    tmp_path: Path, record: StoredPost
):
    (tmp_path / FOLDER).mkdir(parents=True)
    store = JsonPostRecords(tmp_path)
    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER)
    write_post_record(tmp_path / FOLDER, record)

    with pytest.raises(ValueError, match=r'[Ff]older|[Aa]lready|[Mm]ove'):
        store.save_post(ALTERNATIVE, record)

    assert not (tmp_path / ALTERNATIVE).exists()
    assert read_post_record(tmp_path / FOLDER) == record


def test_same_prefix_posts_get_distinct_owned_folders(
    tmp_path: Path, record: StoredPost
):
    store = JsonPostRecords(tmp_path)
    other = replace(record, post=replace(record.post, id='abcdefgh-second'))
    assert store.choose_post_folder(record.post) == store.choose_post_folder(other.post)
    store.save_post(FOLDER, record)
    store.save_post(store.choose_post_folder(other.post), other)

    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER, record)
    assert store.find_post('writer', other.post.id) == LocatedPost(ALTERNATIVE, other)


@pytest.mark.parametrize(
    'folder',
    [
        '',
        '/writer/2026-10-12 - Original (abcdefgh)',
        'other/2026-10-12 - Original (abcdefgh)',
        'writer/2026-10-12 - Original (other-id)',
        'writer/not-a-post-folder',
        'writer/2026-02-30 - Original (abcdefgh)',
        f'../{FOLDER}',
        f'./{FOLDER}',
        FOLDER.replace('/', '//'),
        FOLDER.replace('/', '\\'),
        f'{FOLDER}/child',
        f'{FOLDER}/',
        f'{FOLDER}/../2026-10-12 - Original (abcdefgh)',
        f'C:/{FOLDER}',
    ],
)
def test_invalid_relative_folder_is_rejected_without_writes(
    tmp_path: Path, record: StoredPost, folder: str
):
    with pytest.raises(ValueError, match=r'[Ff]older|[Pp]ath|[Aa]uthor|[Ii]d'):
        JsonPostRecords(tmp_path).save_post(folder, record)

    assert list(tmp_path.iterdir()) == []


def test_invalid_record_creates_neither_library_nor_post_folder(
    tmp_path: Path, record: StoredPost
):
    record.post.likes = -1
    root = tmp_path / 'missing-library'
    store = JsonPostRecords(root)

    with pytest.raises(InvalidPostRecordError):
        store.save_post(FOLDER, record)

    assert not root.exists()
    assert store.find_post('writer', record.post.id) is None


def test_corrupt_target_is_not_overwritten_after_choice(
    tmp_path: Path, record: StoredPost
):
    store = JsonPostRecords(tmp_path)
    assert store.find_post('writer', record.post.id) is None
    choice = store.choose_post_folder(record.post)
    target = tmp_path / choice
    target.mkdir(parents=True)
    post_file = target / 'post.json'
    post_file.write_bytes(b'{')

    with pytest.raises(InvalidPostRecordError) as raised:
        store.save_post(choice, record)

    assert str(post_file) in str(raised.value)
    assert post_file.read_bytes() == b'{'
    assert [path.name for path in target.iterdir()] == ['post.json']


def test_failed_first_publication_indexes_the_orphan_and_retry_reuses_it(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    store = JsonPostRecords(tmp_path)
    assert store.find_post('writer', record.post.id) is None
    error = OSError('publication failed')
    with monkeypatch.context() as patches:
        patches.setattr(Path, 'replace', Mock(side_effect=error))
        with pytest.raises(OSError, match='publication failed') as raised:
            store.save_post(FOLDER, record)
        assert raised.value is error

    record.post.title = 'Renamed after the failed save'
    orphan = store.find_post('writer', record.post.id)
    assert orphan == LocatedPost(FOLDER)
    assert store.find_post('writer', 'abcdefgh-second') == LocatedPost(FOLDER)
    assert list((tmp_path / FOLDER).iterdir()) == []
    assert orphan is not None
    store.save_post(orphan.folder, record)
    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER, record)
    assert store.find_post('writer', 'abcdefgh-second') is None
    assert [path.name for path in (tmp_path / 'writer').iterdir()] == [
        Path(FOLDER).name
    ]


def test_failed_save_does_not_claim_full_identity_for_an_orphan(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    store = JsonPostRecords(tmp_path)
    with monkeypatch.context() as patches:
        patches.setattr(Path, 'replace', Mock(side_effect=OSError('disk full')))
        with pytest.raises(OSError, match='disk full'):
            store.save_post(FOLDER, record)
    other = replace(record, post=replace(record.post, id='abcdefgh-second'))

    store.save_post(FOLDER, other)

    assert store.find_post('writer', record.post.id) is None
    assert store.find_post('writer', other.post.id) == LocatedPost(FOLDER, other)


def test_directory_creation_failure_does_not_leave_a_phantom_post(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    store = JsonPostRecords(tmp_path)
    with monkeypatch.context() as patches:
        patches.setattr(
            Path, 'mkdir', Mock(side_effect=PermissionError('mkdir denied'))
        )
        with pytest.raises(PermissionError, match='mkdir denied'):
            store.save_post(FOLDER, record)

    assert store.find_post('writer', record.post.id) is None
    assert list(tmp_path.iterdir()) == []


def test_index_bookkeeping_does_not_mask_the_publication_error(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    store = JsonPostRecords(tmp_path)
    target = tmp_path / FOLDER
    real_stat = Path.stat
    publication_failed = False
    error = OSError('primary publication failure')
    inspection_error = PermissionError('index bookkeeping denied')

    def fail_replace(_source: Path, _destination: Path) -> None:
        nonlocal publication_failed
        publication_failed = True
        raise error

    def fail_later_stat(path: Path, *, follow_symlinks: bool = True) -> stat_result:
        if publication_failed and path == target:
            raise inspection_error
        return real_stat(path, follow_symlinks=follow_symlinks)

    with monkeypatch.context() as patches:
        patches.setattr(Path, 'replace', fail_replace)
        patches.setattr(Path, 'stat', fail_later_stat)
        with pytest.raises(OSError, match='primary publication failure') as raised:
            store.save_post(FOLDER, record)
        assert raised.value is error

    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER)
    store.save_post(FOLDER, record)
    assert store.find_post('writer', record.post.id) == LocatedPost(FOLDER, record)


@pytest.mark.parametrize('link_location', LinkLocation)
def test_save_rejects_links_outside_library_without_changing_target(
    tmp_path: Path, record: StoredPost, link_location: LinkLocation
):
    root = tmp_path / 'library'
    outside = tmp_path / 'outside'
    outside.mkdir()
    sentinel = outside / 'post.json'
    write_post_record(outside, record)
    before = sentinel.read_bytes()
    match link_location:
        case LinkLocation.author:
            root.mkdir()
            _symlink(root / 'writer', outside)
        case LinkLocation.post:
            (root / 'writer').mkdir(parents=True)
            _symlink(root / FOLDER, outside)
        case LinkLocation.record:
            (root / FOLDER).mkdir(parents=True)
            _symlink(root / FOLDER / 'post.json', sentinel, is_directory=False)
    with pytest.raises(ValueError, match=r'[Rr]oot|[Ll]ibrary|[Oo]utside'):
        JsonPostRecords(root).save_post(FOLDER, record)
    assert sentinel.read_bytes() == before
    assert [path.name for path in outside.iterdir()] == ['post.json']


def test_save_does_not_overwrite_a_file_occupying_the_post_folder(
    tmp_path: Path, record: StoredPost
):
    target = tmp_path / FOLDER
    target.parent.mkdir()
    target.write_bytes(b'user file')

    with pytest.raises(
        (ValueError, NotADirectoryError, FileExistsError, PermissionError)
    ):
        JsonPostRecords(tmp_path).save_post(FOLDER, record)

    assert target.read_bytes() == b'user file'


def test_save_does_not_replace_a_dangling_post_folder_link(
    tmp_path: Path, record: StoredPost
):
    target = tmp_path / FOLDER
    target.parent.mkdir()
    missing = tmp_path / 'missing'
    _symlink(target, missing)

    with pytest.raises((ValueError, NotADirectoryError, FileExistsError)):
        JsonPostRecords(tmp_path).save_post(FOLDER, record)

    assert target.is_symlink()
    assert not missing.exists()
