"""Read-only media observations preserve files and confirm filesystem aliases."""

import os
import subprocess
import sys
from dataclasses import dataclass
from errno import EACCES, ENOSYS, EPERM
from os import stat_result
from pathlib import Path
from typing import NoReturn

import pytest

from boosty_downloader.application.media_paths import (
    FileMatch,
    MediaPathHint,
    find_media_file,
    find_recorded_file,
)
from boosty_downloader.domain.disk_snapshot import DiskSnapshot
from boosty_downloader.infrastructure.library import media_snapshot
from boosty_downloader.infrastructure.library.media_snapshot import (
    confirm_media_aliases,
    read_media_snapshot,
)

FOLDER = 'writer/saved-post'


@dataclass(frozen=True, slots=True)
class _EntryState:
    content: bytes | None
    modified_ns: int


def _write(root: Path, relative: str, content: bytes = b'media') -> Path:
    path = root / FOLDER / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _tree_state(root: Path) -> dict[str, _EntryState]:
    return {
        path.relative_to(root).as_posix(): _EntryState(
            content=path.read_bytes() if path.is_file() else None,
            modified_ns=path.stat().st_mtime_ns,
        )
        for path in [root, *root.rglob('*')]
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


def _deny_access(*_args: object, **_kwargs: object) -> NoReturn:
    message = 'fixture access denied'
    raise PermissionError(message)


@pytest.mark.parametrize('existing_root', [False, True])
def test_missing_post_does_not_create_any_folder(
    tmp_path: Path, *, existing_root: bool
) -> None:
    root = tmp_path / 'library'
    if existing_root:
        root.mkdir()
    before = _tree_state(tmp_path)

    assert read_media_snapshot(root, FOLDER) == DiskSnapshot({})
    assert _tree_state(tmp_path) == before


def test_scan_reads_nested_sizes_and_preserves_every_entry(tmp_path: Path) -> None:
    contents = {
        'files/archive.zip': b'archive',
        'files/empty.bin': b'',
        'files/nested/notes.txt': b'personal notes',
        'post.html': b'<p>saved</p>',
        'viewer.json': b'{"favorite": true}',
        'images/.picture.jpg.part': b'incomplete',
        'files/file.part': b'ordinary attachment',
        'images/.cover': b'ordinary hidden image',
    }
    for relative, content in contents.items():
        _write(tmp_path, relative, content)
    before = _tree_state(tmp_path)

    snapshot = read_media_snapshot(tmp_path, FOLDER)

    assert snapshot.files == {path: len(content) for path, content in contents.items()}
    assert {'files', 'files/nested', 'images'} <= snapshot.occupied
    assert snapshot.aliases == {}
    assert find_recorded_file('images/.picture.jpg.part', snapshot) is None
    assert find_recorded_file('files/file.part', snapshot) == FileMatch(
        'files/file.part', len(contents['files/file.part'])
    )
    assert _tree_state(tmp_path) == before


@pytest.mark.parametrize(
    'folder',
    [
        '',
        '.',
        '..',
        '../outside',
        '/outside',
        'C:/outside',
        'writer\\post',
        'writer//post',
    ],
)
def test_unsafe_post_folder_is_rejected(tmp_path: Path, folder: str) -> None:
    with pytest.raises(ValueError, match='portable relative file path'):
        read_media_snapshot(tmp_path, folder)


@pytest.mark.parametrize(
    'query', ['../outside', '/outside', 'files\\outside', 'files/../outside']
)
def test_unsafe_media_query_is_rejected(tmp_path: Path, query: str) -> None:
    _write(tmp_path, 'files/archive.zip')

    with pytest.raises(ValueError, match='portable relative file path'):
        read_media_snapshot(tmp_path, FOLDER, queried_paths=[query])


def test_post_path_that_is_a_file_is_not_an_empty_snapshot(tmp_path: Path) -> None:
    folder = tmp_path / FOLDER
    folder.parent.mkdir()
    folder.write_bytes(b'not a directory')

    with pytest.raises(NotADirectoryError):
        read_media_snapshot(tmp_path, FOLDER)


def test_links_are_occupied_but_their_targets_are_not_scanned(tmp_path: Path) -> None:
    saved = _write(tmp_path, 'files/saved.zip')
    folder = tmp_path / FOLDER
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.bin').write_bytes(b'outside')
    _symlink(folder / 'copy.zip', saved)
    _symlink(folder / 'outside', outside, directory=True)
    _symlink(folder / 'loop', folder, directory=True)
    _symlink(folder / 'broken', outside / 'absent')

    snapshot = read_media_snapshot(tmp_path, FOLDER, queried_paths=['copy.zip'])

    assert snapshot.files == {'files/saved.zip': 5}
    assert {'copy.zip', 'outside', 'loop', 'broken'} <= snapshot.occupied
    assert snapshot.aliases == {}


def test_post_folder_link_cannot_escape_the_library(tmp_path: Path) -> None:
    root = tmp_path / 'library'
    (root / 'writer').mkdir(parents=True)
    outside = tmp_path / 'outside'
    outside.mkdir()
    _symlink(root / FOLDER, outside, directory=True)

    with pytest.raises(ValueError, match='escapes the library root'):
        read_media_snapshot(root, FOLDER)


@pytest.mark.parametrize('directory_link', [False, True])
def test_media_query_rejects_an_unusable_parent(
    tmp_path: Path, *, directory_link: bool
) -> None:
    folder = tmp_path / FOLDER
    folder.mkdir(parents=True)
    parent = folder / 'files'
    if directory_link:
        _symlink(parent, folder, directory=True)
        expected_error = ValueError
    else:
        parent.write_bytes(b'not a directory')
        expected_error = NotADirectoryError

    with pytest.raises(expected_error):
        read_media_snapshot(tmp_path, FOLDER, queried_paths=['files/archive.zip'])


def test_scan_permission_error_is_not_treated_as_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, 'files/archive.zip')
    monkeypatch.setattr(media_snapshot, 'scandir', _deny_access)

    with pytest.raises(PermissionError, match='fixture access denied'):
        read_media_snapshot(tmp_path, FOLDER)


@pytest.mark.parametrize(
    ('observed', 'queried'),
    [
        ('LESSON.zip', 'lesson.zip'),
        ('Cafe\u0301.zip', 'Café.zip'),
        ('straße.zip', 'strasse.zip'),
    ],
    ids=['case', 'unicode-normalization', 'casefold-lookalike'],
)
def test_alias_requires_confirmation_by_the_actual_filesystem(
    tmp_path: Path, observed: str, queried: str
) -> None:
    actual = _write(tmp_path, f'files/{observed}')
    query = f'files/{queried}'
    requested = tmp_path / FOLDER / query
    confirmed = requested.exists() and requested.samefile(actual)

    snapshot = read_media_snapshot(tmp_path, FOLDER, queried_paths=[query])
    actual_name = next(iter(snapshot.files))

    expected = {query: actual_name} if confirmed and query != actual_name else {}
    assert snapshot.aliases == expected


def test_alias_pass_uses_existing_snapshot_and_respects_file_ownership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    actual = _write(tmp_path, 'videos/TITLE.mp4')
    query = 'videos/Title.mp4'
    confirmed = (actual.parent / 'Title.mp4').exists()
    disk = read_media_snapshot(tmp_path, FOLDER)
    monkeypatch.setattr(media_snapshot, 'scandir', _deny_access)

    observed = confirm_media_aliases(tmp_path, FOLDER, disk, [query])
    recovered = find_media_file(
        'boosty_video:abcdefgh-first',
        observed,
        {},
        preferred=MediaPathHint('videos/Title', suffix_from_response=True),
    )

    assert recovered == (FileMatch('videos/TITLE.mp4', 5) if confirmed else None)
    assert disk.aliases == {}
    assert (
        find_media_file(
            'boosty_video:abcdefgh-first',
            observed,
            {'boosty_video:other': 'videos/TITLE.mp4'},
            recorded_path=query,
        )
        is None
    )


def test_alias_stat_permission_error_is_not_treated_as_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path, 'files/LESSON.zip')
    query = tmp_path / FOLDER / 'files/lesson.zip'
    disk = read_media_snapshot(tmp_path, FOLDER)
    real_lstat = Path.lstat

    def guarded_lstat(path: Path) -> stat_result:
        if path == query:
            _deny_access()
        return real_lstat(path)

    monkeypatch.setattr(Path, 'lstat', guarded_lstat)

    with pytest.raises(PermissionError, match='fixture access denied'):
        confirm_media_aliases(tmp_path, FOLDER, disk, ['files/lesson.zip'])


def test_post_folder_link_within_library_keeps_relative_names(tmp_path: Path) -> None:
    _write(tmp_path, 'files/archive.zip')
    alias = 'writer/linked-post'
    _symlink(tmp_path / alias, tmp_path / FOLDER, directory=True)

    assert read_media_snapshot(tmp_path, alias).files == {'files/archive.zip': 5}


def test_observed_file_stat_error_is_not_treated_as_a_deleted_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = _write(tmp_path, 'files/archive.zip')
    real_lstat = Path.lstat

    def guarded_lstat(path: Path) -> stat_result:
        if path == saved:
            _deny_access()
        return real_lstat(path)

    monkeypatch.setattr(Path, 'lstat', guarded_lstat)

    with pytest.raises(PermissionError, match='fixture access denied'):
        read_media_snapshot(tmp_path, FOLDER)


def test_fifo_is_occupied_without_opening_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not hasattr(os, 'mkfifo'):
        pytest.skip('Platform has no FIFO support')
    folder = tmp_path / FOLDER
    folder.mkdir(parents=True)
    os.mkfifo(folder / 'pipe')
    monkeypatch.setattr(Path, 'open', _deny_access)

    snapshot = read_media_snapshot(tmp_path, FOLDER, queried_paths=['pipe'])

    assert snapshot.files == {}
    assert snapshot.occupied == {'pipe'}
    assert snapshot.aliases == {}


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows directory junction')
def test_directory_junction_is_not_traversed(tmp_path: Path) -> None:
    _write(tmp_path, 'files/saved.zip')
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'private.bin').write_bytes(b'outside')
    junction = tmp_path / FOLDER / 'junction'
    shell = Path(os.environ['SYSTEMROOT']) / 'System32' / 'cmd.exe'
    subprocess.run(  # noqa: S603 - Fixed command and pytest-owned paths.
        [str(shell), '/c', 'mklink', '/J', str(junction), str(outside)],
        check=True,
        capture_output=True,
        timeout=10,
    )

    snapshot = read_media_snapshot(tmp_path, FOLDER)

    assert snapshot.files == {'files/saved.zip': 5}
    assert 'junction' in snapshot.occupied


def test_distinct_casefold_equivalent_files_are_not_aliases(tmp_path: Path) -> None:
    upper = _write(tmp_path, 'files/Archive.zip', b'first copy')
    lower = upper.with_name('archive.zip')
    if lower.exists():
        pytest.skip('Filesystem treats the two spellings as one file')
    lower.write_bytes(b'separate copy')

    snapshot = read_media_snapshot(
        tmp_path, FOLDER, queried_paths=['files/Archive.zip', 'files/archive.zip']
    )

    assert snapshot.files == {'files/Archive.zip': 10, 'files/archive.zip': 13}
    assert snapshot.aliases == {}


@pytest.mark.parametrize('query', ['files/missing.zip', 'files/current.zip'])
def test_rechecking_an_alias_drops_stale_mapping_without_changing_input(
    tmp_path: Path, query: str
) -> None:
    _write(tmp_path, 'files/previous.zip')
    _write(tmp_path, 'files/current.zip')
    observed = read_media_snapshot(tmp_path, FOLDER)
    aliases = {
        query: 'files/previous.zip',
        'files/unqueried.zip': 'files/previous.zip',
    }
    original_aliases = dict(aliases)
    disk = DiskSnapshot(observed.files, observed.occupied, aliases)

    result = confirm_media_aliases(tmp_path, FOLDER, disk, [query])

    assert result.aliases == {'files/unqueried.zip': 'files/previous.zip'}
    assert result.files == disk.files
    assert disk.aliases == original_aliases
    assert aliases == original_aliases
