"""The v5 marker never adopts an older library or replaces an existing marker."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from errno import EACCES, ENOSYS, EPERM
from pathlib import Path
from stat import FILE_ATTRIBUTE_REPARSE_POINT
from threading import Barrier
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from boosty_downloader.infrastructure.library import library_format
from boosty_downloader.infrastructure.library.library_format import (
    LIBRARY_FORMAT_VERSION,
    LIBRARY_MARKER_PATH,
    LibraryCompatibilityError,
    check_library_compatibility,
    initialize_library,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from os import stat_result

    from boosty_downloader.infrastructure.media_publication import PublishedFile


@dataclass(frozen=True)
class _NodeState:
    mode: int
    modified_ns: int
    content: bytes | str | None


def _snapshot(root: Path) -> dict[str, _NodeState]:
    states: dict[str, _NodeState] = {}
    for path in (root, *root.rglob('*')):
        info = path.lstat()
        content: bytes | str | None = None
        if path.is_symlink():
            content = str(path.readlink())
        elif path.is_file():
            content = path.read_bytes()
        states[str(path.relative_to(root))] = _NodeState(
            info.st_mode, info.st_mtime_ns, content
        )
    return states


def _marker(root: Path, data: bytes = b'{"format_version": 5}\n') -> Path:
    marker = root / LIBRARY_MARKER_PATH
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_bytes(data)
    return marker


def _symlink(link: Path, target: Path, *, directory: bool = True) -> None:
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


def test_check_missing_root_preserves_every_existing_parent(tmp_path: Path):
    root = tmp_path / 'not-created' / 'library'
    before = _snapshot(tmp_path)

    check_library_compatibility(root)

    assert _snapshot(tmp_path) == before


def test_initialize_creates_complete_marker_once_and_preserves_unrelated_files(
    tmp_path: Path,
):
    root = tmp_path / 'new' / 'library'
    initialize_library(root)
    marker = root / LIBRARY_MARKER_PATH
    assert json.loads(marker.read_bytes()) == {'format_version': LIBRARY_FORMAT_VERSION}
    foreign = marker.parent / 'library.foreign.tmp'
    foreign.write_bytes(b'other process')
    before = _snapshot(root)

    initialize_library(root)
    check_library_compatibility(root)

    assert _snapshot(root) == before
    assert set(marker.parent.iterdir()) == {marker, foreign}


def test_valid_marker_allows_post_folders_without_opening_their_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / 'library'
    _marker(root)
    post = root / 'writer' / '2026-09-28 - Old post (abcdefgh)'
    post.mkdir(parents=True)
    (post / 'post_cache.db').write_bytes(b'legacy bytes')
    (post / 'post.json').write_bytes(b'unreadable saved post')
    before = _snapshot(root)
    scan = Mock(side_effect=AssertionError('marked libraries need no folder scan'))
    monkeypatch.setattr(Path, 'iterdir', scan)

    check_library_compatibility(root)
    initialize_library(root)

    monkeypatch.undo()
    scan.assert_not_called()
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    'name',
    [
        '2026-09-28 - Old post (abcdefgh)',
        '2026-09-28 - Урок 🚀 (a)',
        '2026-09-28 - Cafe\u0301 [2] (a_B-1234)',
    ],
)
@pytest.mark.parametrize('operation', [check_library_compatibility, initialize_library])
def test_older_folders_under_any_author_stop_without_opening_or_changing_contents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    operation: Callable[[Path], None],
):
    root = tmp_path / 'library'
    post = root / 'another-author' / name
    post.mkdir(parents=True)
    (post / 'post_cache.db').write_bytes(b'old cache')
    (post / 'post.json').write_bytes(b'not an adoption signal')
    (root / 'requested-author').mkdir()
    before = _snapshot(root)
    opened = Mock(side_effect=AssertionError('must not open legacy files'))
    monkeypatch.setattr(library_format.os, 'open', opened)

    with pytest.raises(LibraryCompatibilityError) as caught:
        operation(root)

    assert str(root) in str(caught.value)
    assert 'another destination' in str(caught.value)
    assert 'Keep this folder' in str(caught.value)
    assert 'Boosty no longer serves' in str(caught.value)
    opened.assert_not_called()
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    'name',
    [
        '2026-02-30 - Invalid date (abcdef12)',
        '2026-09-28 - No identity',
        '2026-09-28 - Long identity (abcdef123)',
        '2026-09-28 -   (abc)',
        'prefix 2026-09-28 - Not a whole name (abc)',
    ],
)
def test_unrelated_folders_and_recognized_file_names_are_not_older_posts(
    tmp_path: Path, name: str
):
    author = tmp_path / 'writer'
    (author / name).mkdir(parents=True)
    (author / '2026-09-28 - Ordinary file (abc)').write_text('keep', encoding='utf-8')
    before = _snapshot(tmp_path)

    check_library_compatibility(tmp_path)

    assert _snapshot(tmp_path) == before


def test_only_author_post_depth_is_inspected(tmp_path: Path):
    (tmp_path / '2026-09-28 - Too shallow (abc)').mkdir()
    (tmp_path / 'writer' / 'arbitrary' / '2026-09-28 - Too deep (abc)').mkdir(
        parents=True
    )
    before = _snapshot(tmp_path)

    check_library_compatibility(tmp_path)

    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    'data',
    [
        b'',
        b'{',
        b'[]',
        b'null',
        b'{}',
        b'{"format_version": "5"}',
        b'{"format_version": 5.0}',
        b'{"format_version": true}',
        b'{"format_version": 5, "backend": "json"}',
        b'\xff',
        b' ' * 1025,
    ],
)
@pytest.mark.parametrize('operation', [check_library_compatibility, initialize_library])
def test_malformed_marker_is_not_repaired(
    tmp_path: Path, data: bytes, operation: Callable[[Path], None]
):
    marker = _marker(tmp_path, data)
    before = _snapshot(tmp_path)

    with pytest.raises(
        LibraryCompatibilityError, match='Invalid library marker'
    ) as caught:
        operation(tmp_path)

    assert str(marker) in str(caught.value)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('version', [-1, 4, 6])
def test_unsupported_version_is_not_upgraded(tmp_path: Path, version: int):
    marker = _marker(tmp_path, json.dumps({'format_version': version}).encode())
    before = _snapshot(tmp_path)

    with pytest.raises(
        LibraryCompatibilityError, match='Unsupported library format'
    ) as caught:
        initialize_library(tmp_path)

    assert str(marker) in str(caught.value)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('location', ['root', 'service', 'marker'])
def test_wrong_node_kinds_fail_closed(tmp_path: Path, location: str):
    root = tmp_path / 'library'
    if location == 'root':
        root.write_bytes(b'not a directory')
    elif location == 'service':
        root.mkdir()
        (root / LIBRARY_MARKER_PATH.parent).write_bytes(b'not a directory')
    else:
        (root / LIBRARY_MARKER_PATH).mkdir(parents=True)
    before = _snapshot(tmp_path)

    with pytest.raises(LibraryCompatibilityError):
        initialize_library(root)

    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('location', ['service', 'marker', 'author', 'post'])
@pytest.mark.parametrize('broken', [False, True])
def test_linked_entries_are_not_traversed_or_changed(
    tmp_path: Path, location: str, *, broken: bool
):
    root = tmp_path / 'library'
    root.mkdir()
    target = tmp_path / 'outside'
    if not broken:
        target.mkdir()
    links = {
        'service': root / LIBRARY_MARKER_PATH.parent,
        'marker': root / LIBRARY_MARKER_PATH,
        'author': root / 'writer',
        'post': root / 'writer' / 'arbitrary',
    }
    link = links[location]
    link.parent.mkdir(parents=True, exist_ok=True)
    _symlink(link, target)
    before = _snapshot(tmp_path)

    with pytest.raises(LibraryCompatibilityError, match=r'link|ordinary file'):
        initialize_library(root)

    assert _snapshot(tmp_path) == before


def test_explicit_root_alias_resolves_to_the_same_library(tmp_path: Path):
    actual = tmp_path / 'actual'
    actual.mkdir()
    alias = tmp_path / 'alias'
    _symlink(alias, actual)

    initialize_library(alias)
    before = _snapshot(actual)
    check_library_compatibility(alias)
    initialize_library(actual)

    assert _snapshot(actual) == before
    assert alias.is_symlink()


def test_reparse_marker_is_rejected_without_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    marker = _marker(tmp_path)
    original = Path.lstat

    def reparse(path: Path) -> object:
        info = original(path)
        if path == marker:
            return SimpleNamespace(
                st_mode=info.st_mode, st_file_attributes=FILE_ATTRIBUTE_REPARSE_POINT
            )
        return info

    monkeypatch.setattr(Path, 'lstat', reparse)
    opened = Mock(side_effect=AssertionError('must not open reparse points'))
    monkeypatch.setattr(library_format.os, 'open', opened)

    with pytest.raises(LibraryCompatibilityError, match='ordinary file'):
        check_library_compatibility(tmp_path)

    opened.assert_not_called()


def test_unreadable_marker_is_not_repaired(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _marker(tmp_path)
    before = _snapshot(tmp_path)
    monkeypatch.setattr(
        library_format.os, 'open', Mock(side_effect=PermissionError('denied'))
    )

    with pytest.raises(LibraryCompatibilityError, match='denied'):
        initialize_library(tmp_path)

    assert _snapshot(tmp_path) == before


def test_unreadable_author_scan_is_not_treated_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    author = tmp_path / 'writer'
    author.mkdir()
    original = Path.iterdir

    def deny_author(path: Path) -> Iterator[Path]:
        if path == author:
            message = 'author denied'
            raise PermissionError(message)
        return original(path)

    monkeypatch.setattr(Path, 'iterdir', deny_author)
    before = _snapshot(tmp_path)

    with pytest.raises(LibraryCompatibilityError, match='author denied'):
        initialize_library(tmp_path)

    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    'winner',
    [b'{"format_version": 5}\n', b'{"format_version": 6}\n', b'invalid winner'],
)
def test_publication_race_validates_winner_without_overwriting_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, winner: bytes
):
    publish = library_format.publish_completed_file

    def publish_after_winner(source: Path, destination: Path) -> PublishedFile:
        destination.write_bytes(winner)
        return publish(source, destination)

    monkeypatch.setattr(library_format, 'publish_completed_file', publish_after_winner)

    if winner == b'{"format_version": 5}\n':
        initialize_library(tmp_path)
    else:
        with pytest.raises(LibraryCompatibilityError):
            initialize_library(tmp_path)

    marker = tmp_path / LIBRARY_MARKER_PATH
    assert marker.read_bytes() == winner
    assert set(marker.parent.iterdir()) == {marker}


def test_failed_publication_cleans_only_its_own_temporary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service = tmp_path / LIBRARY_MARKER_PATH.parent
    service.mkdir()
    foreign = service / 'library.foreign.tmp'
    foreign.write_bytes(b'other writer')
    monkeypatch.setattr(
        library_format,
        'publish_completed_file',
        Mock(side_effect=OSError('publication failed')),
    )

    with pytest.raises(LibraryCompatibilityError, match='publication failed'):
        initialize_library(tmp_path)

    assert set(service.iterdir()) == {foreign}
    assert foreign.read_bytes() == b'other writer'


def test_parent_link_swap_before_publication_preserves_outside_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / 'library'
    service = root / LIBRARY_MARKER_PATH.parent
    moved = tmp_path / 'moved-service'
    outside = tmp_path / 'outside'
    outside.mkdir()
    original_publish = library_format._publish_or_validate  # pyright: ignore[reportPrivateUsage]

    def swap_parent(library: Path, temporary: Path) -> None:
        service.rename(moved)
        _symlink(service, outside)
        (outside / temporary.name).write_bytes(b'foreign file with same name')
        original_publish(library, temporary)

    monkeypatch.setattr(library_format, '_publish_or_validate', swap_parent)

    with pytest.raises(LibraryCompatibilityError, match='must not be a symbolic link'):
        initialize_library(root)

    assert not (outside / LIBRARY_MARKER_PATH.name).exists()
    assert [p.read_bytes() for p in outside.iterdir()] == [
        b'foreign file with same name'
    ]
    assert len(list(moved.iterdir())) == 1


def test_marker_swap_between_inspection_and_open_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    marker = _marker(tmp_path)
    other = tmp_path / 'other-marker'
    other.write_bytes(b'{"format_version": 5}')
    original_open = library_format.os.open

    def swap_marker(path: Path, flags: int) -> int:
        if path == marker:
            marker.unlink()
            _symlink(marker, other, directory=False)
        return original_open(path, flags)

    monkeypatch.setattr(library_format.os, 'open', swap_marker)

    with pytest.raises(LibraryCompatibilityError):
        check_library_compatibility(tmp_path)

    assert other.read_bytes() == b'{"format_version": 5}'


def test_concurrent_initializers_publish_one_complete_immutable_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    barrier = Barrier(2)
    publish = library_format.publish_completed_file

    def publish_together(source: Path, destination: Path) -> PublishedFile:
        barrier.wait(timeout=10)
        return publish(source, destination)

    monkeypatch.setattr(library_format, 'publish_completed_file', publish_together)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(initialize_library, tmp_path) for _ in range(2)]
        for future in futures:
            future.result(timeout=15)

    marker = tmp_path / LIBRARY_MARKER_PATH
    assert json.loads(marker.read_bytes()) == {'format_version': LIBRARY_FORMAT_VERSION}
    assert set(marker.parent.iterdir()) == {marker}


def test_disappearing_scan_entry_does_not_turn_a_new_library_into_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    service = tmp_path / LIBRARY_MARKER_PATH.parent
    service.mkdir()
    temporary = service / 'library.other-writer.tmp'
    temporary.touch()
    original_lstat = Path.lstat

    def remove_temporary(path: Path) -> stat_result:
        if path == temporary:
            temporary.unlink(missing_ok=True)
        return original_lstat(path)

    monkeypatch.setattr(Path, 'lstat', remove_temporary)

    initialize_library(tmp_path)

    assert (tmp_path / LIBRARY_MARKER_PATH).is_file()
