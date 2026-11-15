"""Author metadata writes preserve unrelated records, assets and saved posts."""

from dataclasses import replace
from datetime import datetime, timezone
from enum import Enum
from errno import EACCES, ENOSYS, EPERM
from pathlib import Path
from unittest.mock import Mock

import pytest

from boosty_downloader.domain.stored_post import AuthorInfo, LockedPost, PostMetadata
from boosty_downloader.infrastructure.library._author_json import (
    decode_locked_posts,
    encode_author_record,
    encode_locked_posts,
)
from boosty_downloader.infrastructure.library.author_records import (
    clear_locked_post,
    read_author_record,
    read_locked_posts,
    save_locked_post,
    write_author_record,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidAuthorRecordError,
    UnsupportedAuthorSchemaError,
)

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
FIRST_ID = 'abcdefgh-first'
SECOND_ID = 'abcdefgh-second'
SERVICE_FOLDER = 'writer/.boosty-downloader'


class Operation(Enum):
    read_author = 'read_author'
    write_author = 'write_author'
    read_locked = 'read_locked'
    save_locked = 'save_locked'
    clear_locked = 'clear_locked'

    @property
    def filename(self) -> str:
        if self in {Operation.read_author, Operation.write_author}:
            return 'author.json'
        return 'locked.json'


class BadRecord(Enum):
    corrupt = 'corrupt'
    unsupported = 'unsupported'
    foreign = 'foreign'


class LinkLocation(Enum):
    author = 'author'
    service = 'service'
    record = 'record'


def _author() -> AuthorInfo:
    return AuthorInfo(
        'writer',
        NOW,
        title='Уроки',
        owner_name='Автор',
        description='About the blog',
        avatar_path='.boosty-downloader/avatar.jpg',
        cover_path='.boosty-downloader/cover.png',
        remote_post_count=12,
    )


def _locked(post_id: str = FIRST_ID, *, author: str = 'writer') -> LockedPost:
    return LockedPost(
        PostMetadata(
            post_id,
            author,
            f'https://boosty.to/{author}/posts/{post_id}',
            'Закрытый урок',
            NOW,
            NOW,
            tags=['lesson'],
        ),
        NOW,
        f'.boosty-downloader/teasers/{post_id}.jpg',
    )


def _run(operation: Operation, root: Path) -> object:
    match operation:
        case Operation.read_author:
            return read_author_record(root, 'writer')
        case Operation.write_author:
            return write_author_record(root, _author())
        case Operation.read_locked:
            return read_locked_posts(root, 'writer')
        case Operation.save_locked:
            return save_locked_post(root, _locked())
        case Operation.clear_locked:
            return clear_locked_post(root, 'writer', FIRST_ID)


def _seed(root: Path, relative: str, data: bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


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


def _bad_bytes(operation: Operation, problem: BadRecord) -> bytes:
    match problem:
        case BadRecord.corrupt:
            return b'{broken'
        case BadRecord.unsupported:
            return b'{"schema_version": 2}'
        case BadRecord.foreign:
            if operation in {Operation.read_author, Operation.write_author}:
                return encode_author_record(replace(_author(), author='other'))
            return encode_locked_posts('other', {})


def test_missing_reads_and_clear_create_no_library(tmp_path: Path):
    root = tmp_path / 'absent'

    assert read_author_record(root, 'writer') is None
    assert read_locked_posts(root, 'writer') == {}
    clear_locked_post(root, 'writer', FIRST_ID)

    assert not root.exists()


def test_author_write_replaces_complete_snapshot_and_preserves_other_authors(
    tmp_path: Path,
):
    author = _author()
    other = replace(author, author='other')
    write_author_record(tmp_path, author)
    write_author_record(tmp_path, other)
    other_before = _snapshot(tmp_path / 'other')
    replacement = AuthorInfo('writer', NOW, title='New title')

    write_author_record(tmp_path, replacement)

    assert read_author_record(tmp_path, 'writer') == replacement
    assert _snapshot(tmp_path / 'other') == other_before
    assert read_author_record(tmp_path, 'other') == other
    assert author == _author()


def test_relative_root_and_missing_optional_images(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    root = Path('library')
    write_author_record(root, _author())
    save_locked_post(root, _locked())

    assert read_author_record(root, 'writer') == _author()
    assert read_locked_posts(root, 'writer') == {FIRST_ID: _locked()}
    assert {path.relative_to(root).as_posix() for path in root.rglob('*')} == {
        'writer',
        SERVICE_FOLDER,
        f'{SERVICE_FOLDER}/author.json',
        f'{SERVICE_FOLDER}/locked.json',
    }


def test_locked_only_post_creates_service_record_without_post_folder(tmp_path: Path):
    save_locked_post(tmp_path, _locked())

    assert {path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob('*')} == {
        'writer',
        SERVICE_FOLDER,
        f'{SERVICE_FOLDER}/locked.json',
    }


def test_locked_upsert_and_clear_use_full_ids_and_fresh_records(tmp_path: Path):
    first, second = _locked(), _locked(SECOND_ID)
    save_locked_post(tmp_path, first)
    path = tmp_path / SERVICE_FOLDER / 'locked.json'
    path.write_bytes(
        encode_locked_posts('writer', {FIRST_ID: first, SECOND_ID: second})
    )
    updated = replace(
        first, post=replace(first.post, title='Updated lesson'), teaser_path=None
    )

    save_locked_post(tmp_path, updated)

    assert read_locked_posts(tmp_path, 'writer') == {
        FIRST_ID: updated,
        SECOND_ID: second,
    }
    external = _locked('external-post')
    path.write_bytes(
        encode_locked_posts(
            'writer',
            {
                FIRST_ID: updated,
                SECOND_ID: second,
                external.post.id: external,
            },
        )
    )
    clear_locked_post(tmp_path, 'writer', FIRST_ID)
    assert read_locked_posts(tmp_path, 'writer') == {
        SECOND_ID: second,
        external.post.id: external,
    }
    assert first == _locked()


def test_locked_updates_preserve_other_authors_with_the_same_post_id(tmp_path: Path):
    other = _locked(author='other')
    save_locked_post(tmp_path, other)
    before = _snapshot(tmp_path / 'other')

    save_locked_post(tmp_path, _locked())
    clear_locked_post(tmp_path, 'writer', FIRST_ID)

    assert _snapshot(tmp_path / 'other') == before
    assert read_locked_posts(tmp_path, 'other') == {FIRST_ID: other}


def test_clear_absent_id_does_not_rewrite_existing_metadata(tmp_path: Path):
    save_locked_post(tmp_path, _locked())
    before = _snapshot(tmp_path)
    path = tmp_path / SERVICE_FOLDER / 'locked.json'
    modified = path.stat().st_mtime_ns
    tree = set(tmp_path.rglob('*'))

    clear_locked_post(tmp_path, 'writer', 'unseen-post')

    assert _snapshot(tmp_path) == before
    assert path.stat().st_mtime_ns == modified
    assert set(tmp_path.rglob('*')) == tree


def test_clear_last_entry_keeps_valid_empty_document(tmp_path: Path):
    save_locked_post(tmp_path, _locked())

    clear_locked_post(tmp_path, 'writer', FIRST_ID)

    path = tmp_path / SERVICE_FOLDER / 'locked.json'
    assert decode_locked_posts(path.read_bytes(), author='writer') == {}
    assert read_locked_posts(tmp_path, 'writer') == {}


def test_metadata_updates_preserve_saved_content_viewing_marks_and_assets(
    tmp_path: Path,
):
    retained = {
        'writer/lesson/post.json': b'{"saved": "body"}',
        'writer/lesson/post.html': b'<p>Saved lesson</p>',
        'writer/lesson/video.mp4': b'video',
        'writer/lesson/viewer.json': b'{"favorite": true}',
        f'{SERVICE_FOLDER}/avatar.jpg': b'avatar',
        f'{SERVICE_FOLDER}/cover.png': b'cover',
        f'{SERVICE_FOLDER}/teasers/{FIRST_ID}.jpg': b'teaser',
    }
    for relative, data in retained.items():
        _seed(tmp_path, relative, data)

    write_author_record(tmp_path, _author())
    save_locked_post(tmp_path, _locked())
    clear_locked_post(tmp_path, 'writer', FIRST_ID)

    assert {
        relative: (tmp_path / relative).read_bytes() for relative in retained
    } == retained


@pytest.mark.parametrize('operation', list(Operation))
@pytest.mark.parametrize('problem', list(BadRecord))
def test_invalid_existing_record_is_not_replaced(
    tmp_path: Path, operation: Operation, problem: BadRecord
):
    path = _seed(
        tmp_path,
        f'{SERVICE_FOLDER}/{operation.filename}',
        _bad_bytes(operation, problem),
    )
    before = _snapshot(tmp_path)
    expected: type[InvalidAuthorRecordError] = InvalidAuthorRecordError
    if problem is BadRecord.unsupported:
        expected = UnsupportedAuthorSchemaError

    with pytest.raises(expected) as raised:
        _run(operation, tmp_path)

    assert str(path) in str(raised.value)
    assert _snapshot(tmp_path) == before


def test_clear_absent_id_still_checks_existing_record(tmp_path: Path):
    path = _seed(tmp_path, f'{SERVICE_FOLDER}/locked.json', b'{broken')

    with pytest.raises(InvalidAuthorRecordError) as raised:
        clear_locked_post(tmp_path, 'writer', 'unseen-post')

    assert str(path) in str(raised.value)
    assert path.read_bytes() == b'{broken'


def test_invalid_author_input_fails_before_creating_directories(tmp_path: Path):
    root = tmp_path / 'absent'

    with pytest.raises(InvalidAuthorRecordError, match=r'author\.json'):
        write_author_record(root, replace(_author(), remote_post_count=-1))

    assert not root.exists()


def test_invalid_locked_input_fails_before_creating_directories(tmp_path: Path):
    root = tmp_path / 'absent'

    with pytest.raises(InvalidAuthorRecordError, match=r'locked\.json'):
        save_locked_post(root, replace(_locked(), teaser_path='../outside.jpg'))

    assert not root.exists()


@pytest.mark.parametrize('operation', list(Operation))
@pytest.mark.parametrize('location', list(LinkLocation))
def test_escaping_symlinks_are_rejected(
    tmp_path: Path, operation: Operation, location: LinkLocation
):
    root, outside = tmp_path / 'library', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    target = outside
    match location:
        case LinkLocation.author:
            link = root / 'writer'
        case LinkLocation.service:
            link = root / SERVICE_FOLDER
        case LinkLocation.record:
            link = root / SERVICE_FOLDER / operation.filename
            target = _seed(outside, operation.filename, b'preserved')
    link.parent.mkdir(parents=True, exist_ok=True)
    _symlink(link, target, is_directory=location is not LinkLocation.record)
    before = _snapshot(outside)

    with pytest.raises(ValueError, match='escapes'):
        _run(operation, root)

    assert link.is_symlink()
    assert _snapshot(outside) == before


def test_service_escape_is_rejected_when_record_link_returns_inside_library(
    tmp_path: Path,
):
    root, outside = tmp_path / 'library', tmp_path / 'outside'
    original = encode_author_record(replace(_author(), title='Previous title'))
    retained = _seed(root, 'retained-author.json', original)
    outside.mkdir()
    service = root / SERVICE_FOLDER
    service.parent.mkdir(parents=True)
    _symlink(service, outside, is_directory=True)
    record_link = outside / 'author.json'
    _symlink(record_link, retained, is_directory=False)

    with pytest.raises(ValueError, match='escapes'):
        write_author_record(root, _author())

    assert retained.read_bytes() == original
    assert service.is_symlink()
    assert record_link.is_symlink()
    assert list(outside.iterdir()) == [record_link]


@pytest.mark.parametrize('operation', list(Operation))
def test_record_directory_is_not_treated_as_missing(
    tmp_path: Path, operation: Operation
):
    path = tmp_path / SERVICE_FOLDER / operation.filename
    path.mkdir(parents=True)

    with pytest.raises(OSError):  # noqa: PT011 - Native directory-read error varies by platform.
        _run(operation, tmp_path)

    assert path.is_dir()
    assert list(path.iterdir()) == []


@pytest.mark.parametrize('operation', list(Operation))
def test_read_permission_error_is_not_treated_as_missing(
    tmp_path: Path, operation: Operation, monkeypatch: pytest.MonkeyPatch
):
    denied = PermissionError(EACCES, 'read denied')
    monkeypatch.setattr(Path, 'read_bytes', Mock(side_effect=denied))

    with pytest.raises(PermissionError, match='read denied') as raised:
        _run(operation, tmp_path)

    assert raised.value is denied
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    'operation', [Operation.write_author, Operation.save_locked, Operation.clear_locked]
)
def test_failed_replacement_preserves_previous_metadata_and_unrelated_files(
    tmp_path: Path, operation: Operation, monkeypatch: pytest.MonkeyPatch
):
    write_author_record(tmp_path, replace(_author(), title='Previous title'))
    save_locked_post(tmp_path, replace(_locked(), teaser_path=None))
    _seed(tmp_path, f'{SERVICE_FOLDER}/avatar.jpg', b'avatar')
    before = _snapshot(tmp_path)
    replace_file = Mock(side_effect=OSError('replace failed'))
    monkeypatch.setattr(Path, 'replace', replace_file)

    with pytest.raises(OSError, match='replace failed'):
        _run(operation, tmp_path)

    replace_file.assert_called_once()
    assert _snapshot(tmp_path) == before
    assert list(tmp_path.rglob('*.tmp')) == []
