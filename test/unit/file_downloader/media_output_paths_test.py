"""Reserved media destinations preserve names and reject unsafe filesystem parents."""

import errno
from os import stat_result
from pathlib import Path
from stat import FILE_ATTRIBUTE_REPARSE_POINT
from types import SimpleNamespace
from typing import Literal, cast

import pytest

from boosty_downloader.infrastructure.media_output_paths import (
    create_media_parent,
    resolve_media_destination,
)

FOLDER = 'writer/post'
MEDIA = 'files/archive.zip'


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except NotImplementedError:
        pytest.skip('Filesystem does not support symlinks')
    except OSError as error:
        if (
            error.errno in {errno.EPERM, errno.EACCES}
            or getattr(error, 'winerror', None) == 1314
        ):
            pytest.skip('Filesystem does not permit symlinks')
        raise


def test_resolution_does_not_create_missing_folders(tmp_path: Path) -> None:
    root = tmp_path / 'library'

    assert resolve_media_destination(root, FOLDER, MEDIA) == root / FOLDER / MEDIA
    assert not root.exists()


def test_parent_creation_builds_the_missing_tree(tmp_path: Path) -> None:
    root = tmp_path / 'library'

    destination = create_media_parent(root, FOLDER, MEDIA)

    assert destination == root / FOLDER / MEDIA
    assert destination.parent.is_dir()
    assert not destination.exists()


@pytest.mark.parametrize(
    'unsafe',
    [
        '',
        '.',
        '..',
        '../escape',
        '/absolute',
        'C:/absolute',
        'C:drive',
        'files\\name',
        'files//name',
        'files/./name',
        'files/../name',
        'files/name\0',
        'files/name:stream',
        'files/CON.txt',
        'files/NUL',
        'files/name.',
        'files/name ',
        'files/ name',
        'files/na?me',
    ],
)
@pytest.mark.parametrize('is_post_folder', [False, True])
def test_unsafe_names_fail_before_creating_folders(
    tmp_path: Path, unsafe: str, *, is_post_folder: bool
) -> None:
    root = tmp_path / 'library'
    folder, media = (unsafe, MEDIA) if is_post_folder else (FOLDER, unsafe)

    with pytest.raises(ValueError, match='portable'):
        create_media_parent(root, folder, media)

    assert not root.exists()


@pytest.mark.parametrize('name', ['Cafe\u0301.zip', 'a' * 250])
def test_safe_names_keep_their_spelling_and_existing_length(
    tmp_path: Path, name: str
) -> None:
    relative = f'files/{name}'

    destination = create_media_parent(tmp_path, FOLDER, relative)

    assert destination == tmp_path / FOLDER / relative
    assert destination.name == name


@pytest.mark.parametrize('entry_kind', ['file', 'directory', 'broken-link'])
def test_occupied_final_entry_is_readable_but_never_replaceable(
    tmp_path: Path, entry_kind: Literal['file', 'directory', 'broken-link']
) -> None:
    destination = tmp_path / FOLDER / MEDIA
    destination.parent.mkdir(parents=True)
    match entry_kind:
        case 'file':
            destination.write_bytes(b'keep')
        case 'directory':
            destination.mkdir()
        case 'broken-link':
            _symlink(destination, tmp_path.parent / 'missing')

    assert resolve_media_destination(tmp_path, FOLDER, MEDIA) == destination
    with pytest.raises(FileExistsError):
        create_media_parent(tmp_path, FOLDER, MEDIA)
    assert destination.lstat()
    if entry_kind == 'file':
        assert destination.read_bytes() == b'keep'


def test_inward_post_link_uses_the_same_destination(tmp_path: Path) -> None:
    actual = tmp_path / FOLDER
    actual.mkdir(parents=True)
    _symlink(tmp_path / 'writer/alias', actual)

    assert create_media_parent(tmp_path, 'writer/alias', MEDIA) == actual / MEDIA
    assert (actual / 'files').is_dir()


def test_outward_post_link_is_rejected_before_writing(tmp_path: Path) -> None:
    root, outside = tmp_path / 'library', tmp_path / 'outside'
    (root / 'writer').mkdir(parents=True)
    outside.mkdir()
    _symlink(root / FOLDER, outside)

    with pytest.raises(ValueError, match='escapes the library root'):
        create_media_parent(root, FOLDER, MEDIA)
    assert list(outside.iterdir()) == []


@pytest.mark.parametrize('inward', [False, True])
def test_media_directory_links_are_never_traversed(
    tmp_path: Path, *, inward: bool
) -> None:
    root = tmp_path / 'library'
    folder = root / FOLDER
    folder.mkdir(parents=True)
    target = folder / 'other' if inward else tmp_path / 'outside'
    target.mkdir()
    _symlink(folder / 'files', target)

    with pytest.raises(ValueError, match='directory link'):
        create_media_parent(root, FOLDER, MEDIA)
    assert list(target.iterdir()) == []


def test_regular_file_cannot_be_a_media_parent(tmp_path: Path) -> None:
    parent = tmp_path / FOLDER / 'files'
    parent.parent.mkdir(parents=True)
    parent.write_bytes(b'keep')

    with pytest.raises(NotADirectoryError):
        create_media_parent(tmp_path, FOLDER, MEDIA)
    assert parent.read_bytes() == b'keep'


def test_parent_stat_failure_is_not_treated_as_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'library'
    parent = root / FOLDER / 'files'
    real_lstat = Path.lstat

    def denied_lstat(path: Path) -> stat_result:
        if path == parent:
            message = 'fixture access denied'
            raise PermissionError(message)
        return real_lstat(path)

    monkeypatch.setattr(Path, 'lstat', denied_lstat)
    with pytest.raises(PermissionError, match='fixture access denied'):
        create_media_parent(root, FOLDER, MEDIA)
    assert not root.exists()


def test_reparse_directory_is_rejected_on_every_platform(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / FOLDER / 'files'
    parent.mkdir(parents=True)
    real_lstat = Path.lstat

    def reparse_lstat(path: Path) -> stat_result:
        info = real_lstat(path)
        if path == parent:
            return cast(
                'stat_result',
                SimpleNamespace(
                    st_mode=info.st_mode,
                    st_file_attributes=FILE_ATTRIBUTE_REPARSE_POINT,
                ),
            )
        return info

    monkeypatch.setattr(Path, 'lstat', reparse_lstat)
    with pytest.raises(ValueError, match='directory link'):
        create_media_parent(tmp_path, FOLDER, MEDIA)


def test_directory_created_as_a_link_is_rejected_before_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / FOLDER / 'files'
    outside = tmp_path / 'outside'
    outside.mkdir()
    real_mkdir = Path.mkdir

    def competing_mkdir(path: Path, *, exist_ok: bool = False) -> None:
        if path == parent:
            _symlink(path, outside)
            return
        real_mkdir(path, exist_ok=exist_ok)

    monkeypatch.setattr(Path, 'mkdir', competing_mkdir)
    with pytest.raises(ValueError, match='directory link'):
        create_media_parent(tmp_path, FOLDER, MEDIA)
    assert list(outside.iterdir()) == []
