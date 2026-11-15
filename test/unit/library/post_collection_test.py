"""Offline record enumeration is independent of indexes and viewing metadata."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from errno import EACCES, ENOSYS, EPERM
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.domain.library import SavedPost
from boosty_downloader.domain.post_folder import compose_post_directory_name
from boosty_downloader.domain.stored_post import PostMetadata, PostSync, StoredPost
from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidPostRecordError,
)
from boosty_downloader.infrastructure.library.json_store import write_post_record
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

if TYPE_CHECKING:
    from collections.abc import Iterator

    from boosty_downloader.application.ports import StoredPostCollection

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
POST_ID = 'abcdefgh-first'


@dataclass(frozen=True, slots=True)
class _FileSnapshot:
    data: bytes
    modified_ns: int


def _record(author: str = 'writer', post_id: str = POST_ID) -> StoredPost:
    return StoredPost(
        PostMetadata(
            post_id,
            author,
            f'https://boosty.to/{author}/posts/{post_id}',
            'Saved lesson',
            NOW,
            NOW,
            tags=['lesson'],
            content_counters={'file': 1},
        ),
        PostSync(NOW, NOW),
    )


def _seed(root: Path, record: StoredPost, *, collision: int = 0) -> Path:
    folder = (
        root
        / record.post.author
        / compose_post_directory_name(
            record.post.title,
            record.post.created_at,
            record.post.id,
            collision=collision,
        )
    )
    write_post_record(folder, record, create_folder=True)
    return folder


def _snapshot(root: Path) -> dict[Path, _FileSnapshot]:
    return {
        path.relative_to(root): _FileSnapshot(
            path.read_bytes(), path.stat().st_mtime_ns
        )
        for path in root.rglob('*')
        if path.is_file()
    }


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


def test_collection_matches_narrow_port_and_reads_every_author(tmp_path: Path) -> None:
    first = _record()
    second = _record('other-writer')
    first_folder = _seed(tmp_path, first)
    second_folder = _seed(tmp_path, second)
    collection: StoredPostCollection = JsonPostRecords(tmp_path)

    assert list(collection.iter_saved_posts()) == [
        SavedPost(second_folder.relative_to(tmp_path).as_posix(), second),
        SavedPost(first_folder.relative_to(tmp_path).as_posix(), first),
    ]
    assert list(collection.iter_saved_posts('writer')) == [
        SavedPost(first_folder.relative_to(tmp_path).as_posix(), first)
    ]
    assert list(collection.iter_saved_posts('absent')) == []


def test_missing_library_and_author_stay_absent(tmp_path: Path) -> None:
    root = tmp_path / 'missing'
    collection = JsonPostRecords(root)
    assert list(collection.iter_saved_posts()) == []
    assert list(collection.iter_saved_posts('writer')) == []
    assert not root.exists()


@pytest.mark.parametrize('author', ['../outside', 'bad/name', 'CON', 'trailing.'])
def test_explicit_author_is_validated_before_enumeration(
    tmp_path: Path, author: str
) -> None:
    with pytest.raises(ValueError, match='portable directory name'):
        list(JsonPostRecords(tmp_path).iter_saved_posts(author))


def test_enumeration_reads_only_canonical_records_and_preserves_all_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _seed(tmp_path, _record())
    service = folder.parent / '.boosty-downloader'
    service.mkdir()
    for name in ('author.json', 'locked.json'):
        (service / name).write_bytes(b'invalid metadata')
    (folder / 'viewer.json').write_bytes(b'invalid viewing marks')
    (folder / 'post.html').write_bytes(b'old page')
    media = folder / 'files'
    media.mkdir()
    (media / 'file.bin').write_bytes(b'kept media')
    root_service = tmp_path / '.boosty-downloader'
    root_service.mkdir()
    (root_service / 'index.db').write_bytes(b'not a database')
    (folder.parent / 'post_cache.db').write_bytes(b'legacy cache')
    before = _snapshot(tmp_path)
    opened: list[Path] = []
    scanned: list[Path] = []
    real_open = os.open
    real_iterdir = Path.iterdir

    def checked_open(path: Path, flags: int) -> int:
        opened.append(path)
        assert path == folder / 'post.json'
        return real_open(path, flags)

    def checked_iterdir(path: Path) -> Iterator[Path]:
        scanned.append(path)
        assert path in {tmp_path, folder.parent}
        return real_iterdir(path)

    with monkeypatch.context() as reads:
        reads.setattr(os, 'open', checked_open)
        reads.setattr(Path, 'iterdir', checked_iterdir)
        posts = list(JsonPostRecords(tmp_path).iter_saved_posts())

    assert len(posts) == 1
    assert opened == [folder / 'post.json']
    assert set(scanned) == {tmp_path, folder.parent}
    assert _snapshot(tmp_path) == before


def test_recordless_and_unrecognized_folders_are_skipped(tmp_path: Path) -> None:
    folder = _seed(tmp_path, _record())
    recordless = folder.with_name('2026-11-09 - Old page (ijklmnop)')
    recordless.mkdir()
    (recordless / 'viewer.json').write_bytes(b'invalid but irrelevant')
    (recordless / 'post.html').write_bytes(b'saved page')
    unrelated = folder.parent / 'notes'
    unrelated.mkdir()
    (unrelated / 'post.json').write_bytes(b'not a recognized post')
    fake_author = tmp_path / 'backup'
    fake_author.mkdir()
    (fake_author / 'readme.txt').write_bytes(b'notes')

    assert [
        item.record.post.id for item in JsonPostRecords(tmp_path).iter_saved_posts()
    ] == [POST_ID]


@pytest.mark.skipif(os.name == 'nt', reason='Windows rejects nonportable names')
@pytest.mark.parametrize('name', ['notes.', 'backup: old'])
def test_nonportable_folder_name_requires_a_canonical_record(
    tmp_path: Path, name: str
) -> None:
    folder = tmp_path / name / '2026-11-09 - Empty (abcdefgh)'
    folder.mkdir(parents=True)
    (folder / 'viewer.json').write_bytes(b'ignored')
    assert list(JsonPostRecords(tmp_path).iter_saved_posts()) == []
    write_post_record(folder, _record())
    with pytest.raises(ValueError, match='portable directory name'):
        list(JsonPostRecords(tmp_path).iter_saved_posts())


@pytest.mark.parametrize('mismatch', ['author', 'prefix'])
def test_canonical_record_must_match_author_and_folder(
    tmp_path: Path, mismatch: str
) -> None:
    record = _record()
    folder = _seed(tmp_path, record)
    match mismatch:
        case 'author':
            record.post.author = 'another'
        case 'prefix':
            record.post.id = 'ijklmnop-other'
        case _:
            pytest.fail(f'Unexpected mismatch: {mismatch}')
    write_post_record(folder, record)
    with pytest.raises(InvalidPostRecordError, match='author and folder'):
        list(JsonPostRecords(tmp_path).iter_saved_posts())


def test_full_ids_with_a_shared_prefix_remain_distinct(tmp_path: Path) -> None:
    first = _record()
    second = _record(post_id='abcdefgh-second')
    _seed(tmp_path, first)
    _seed(tmp_path, second, collision=1)
    assert {
        saved.record.post.id for saved in JsonPostRecords(tmp_path).iter_saved_posts()
    } == {
        first.post.id,
        second.post.id,
    }


def test_duplicate_full_identity_is_rejected_before_the_group_is_yielded(
    tmp_path: Path,
) -> None:
    first = _seed(tmp_path, _record())
    second = _seed(tmp_path, _record(), collision=1)
    iterator = JsonPostRecords(tmp_path).iter_saved_posts()
    with pytest.raises(AmbiguousPostFolderError) as raised:
        next(iterator)
    assert first.relative_to(tmp_path).as_posix() in str(raised.value)
    assert second.relative_to(tmp_path).as_posix() in str(raised.value)


def test_enumeration_is_fresh_after_lookup_cache_and_returns_independent_records(
    tmp_path: Path,
) -> None:
    record = _record()
    folder = _seed(tmp_path, record)
    collection = JsonPostRecords(tmp_path)
    assert collection.find_post('writer', POST_ID) is not None
    renamed = folder.with_name('2026-11-09 - Local rename (abcdefgh)')
    folder.rename(renamed)
    later = _record(post_id='ijklmnop-later')
    _seed(tmp_path, later)
    first = next(collection.iter_saved_posts('writer'))
    first.record.post.tags.append('changed')
    first.record.post.content_counters['file'] = 9
    current = {saved.record.post.id: saved for saved in collection.iter_saved_posts()}
    assert set(current) == {POST_ID, later.post.id}
    assert current[POST_ID].folder == renamed.relative_to(tmp_path).as_posix()
    assert current[POST_ID].record == record
    assert current[later.post.id].record == later


@pytest.mark.parametrize('kind', ['author', 'post', 'record'])
def test_contained_source_aliases_are_supported(tmp_path: Path, kind: str) -> None:
    folder = _seed(tmp_path, _record())
    match kind:
        case 'author':
            link = folder.parent
            target = tmp_path / '.boosty-downloader' / 'author-data'
        case 'post':
            link = folder
            target = folder.parent / 'post-data'
        case 'record':
            link = folder / 'post.json'
            target = folder / 'record-data.json'
        case _:
            pytest.fail(f'Unexpected alias kind: {kind}')
    target.parent.mkdir(parents=True, exist_ok=True)
    link.rename(target)
    _symlink(link, target, directory=kind != 'record')
    posts = list(JsonPostRecords(tmp_path).iter_saved_posts())
    assert posts == [SavedPost(folder.relative_to(tmp_path).as_posix(), _record())]


@pytest.mark.parametrize('kind', ['author', 'post', 'record'])
def test_escaping_source_aliases_are_rejected_without_reading_external_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    root = tmp_path / 'library'
    folder = _seed(root, _record())
    match kind:
        case 'author':
            link = folder.parent
        case 'post':
            link = folder
        case 'record':
            link = folder / 'post.json'
        case _:
            pytest.fail(f'Unexpected alias kind: {kind}')
    target = tmp_path / 'outside'
    link.rename(target)
    _symlink(link, target, directory=kind != 'record')

    def forbidden_open(*_args: object, **_kwargs: object) -> int:
        pytest.fail('Escaping source was opened')

    monkeypatch.setattr(os, 'open', forbidden_open)
    with pytest.raises(ValueError, match='escapes'):
        list(JsonPostRecords(root).iter_saved_posts())


@pytest.mark.parametrize('kind', ['author', 'post', 'record'])
def test_dangling_source_alias_is_not_silently_absent(
    tmp_path: Path, kind: str
) -> None:
    folder = _seed(tmp_path, _record())
    match kind:
        case 'author':
            link = folder.parent
        case 'post':
            link = folder
        case 'record':
            link = folder / 'post.json'
        case _:
            pytest.fail(f'Unexpected alias kind: {kind}')
    link.rename(tmp_path / '.boosty-downloader')
    _symlink(link, tmp_path / 'missing', directory=kind != 'record')
    with pytest.raises(FileNotFoundError):
        list(JsonPostRecords(tmp_path).iter_saved_posts())


def test_contained_post_alias_does_not_hide_a_duplicate_full_identity(
    tmp_path: Path,
) -> None:
    folder = _seed(tmp_path, _record())
    alias = folder.with_name('2026-11-09 - Alias (abcdefgh)')
    _symlink(alias, folder, directory=True)
    with pytest.raises(AmbiguousPostFolderError):
        next(JsonPostRecords(tmp_path).iter_saved_posts())


@pytest.mark.parametrize('contents', [b'{', b'{"schema_version": 9}'])
def test_invalid_record_error_names_its_source(tmp_path: Path, contents: bytes) -> None:
    folder = _seed(tmp_path, _record())
    path = folder / 'post.json'
    path.write_bytes(contents)
    with pytest.raises(InvalidPostRecordError) as raised:
        list(JsonPostRecords(tmp_path).iter_saved_posts())
    assert str(path) in str(raised.value)
    assert path.read_bytes() == contents


def test_record_directory_is_rejected(tmp_path: Path) -> None:
    folder = _seed(tmp_path, _record())
    path = folder / 'post.json'
    path.unlink()
    path.mkdir()
    with pytest.raises(InvalidPostRecordError, match='ordinary file'):
        list(JsonPostRecords(tmp_path).iter_saved_posts())


def test_replaced_record_is_rejected_before_decoding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _seed(tmp_path, _record())
    target = folder / 'post.json'
    replacement = folder / 'replacement.json'
    write_post_record(folder, _record())
    replacement.write_bytes(target.read_bytes())
    real_open = os.open

    def replaced_open(path: Path, flags: int) -> int:
        if path == target:
            replacement.replace(target)
        return real_open(path, flags)

    monkeypatch.setattr(os, 'open', replaced_open)
    with pytest.raises(OSError, match='changed while being read'):
        list(JsonPostRecords(tmp_path).iter_saved_posts())


def test_collection_saves_in_the_existing_confirmed_folder(tmp_path: Path) -> None:
    record = _record()
    folder = _seed(tmp_path, record)
    collection: StoredPostCollection = JsonPostRecords(tmp_path)
    saved = next(collection.iter_saved_posts())
    changed = replace(saved.record, sync=replace(saved.record.sync, page_template=2))
    collection.save_post(saved.folder, changed)
    assert next(collection.iter_saved_posts()).record == changed
    assert folder.is_dir()
