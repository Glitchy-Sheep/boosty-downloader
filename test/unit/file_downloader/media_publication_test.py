"""Completed media appears at its final path without replacing existing files."""

from __future__ import annotations

import errno
import os
import re
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.infrastructure import media_publication
from boosty_downloader.infrastructure.media_publication import (
    PublishedFile,
    publish_completed_file,
)

if TYPE_CHECKING:
    from pathlib import Path

MEDIA_BYTES = b'Completed media bytes'
EXISTING_BYTES = b'An existing user file'


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / '.video.part'
    path.write_bytes(MEDIA_BYTES)
    return path


@pytest.fixture
def destination(tmp_path: Path) -> Path:
    return tmp_path / 'video.mp4'


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target)
    except OSError as error:
        if os.name == 'nt' and error.winerror == 1314:
            pytest.skip('Creating symlinks requires Windows developer mode')
        raise


@pytest.mark.parametrize('data', [MEDIA_BYTES, b''], ids=['nonempty', 'empty'])
def test_publication_reports_final_path_and_actual_size(
    source: Path, destination: Path, data: bytes
) -> None:
    source.write_bytes(data)

    result = publish_completed_file(source, destination)

    assert result == PublishedFile(path=destination, size=len(data))
    assert destination.read_bytes() == data


def test_existing_file_is_preserved_with_its_timestamp(
    source: Path, destination: Path
) -> None:
    destination.write_bytes(EXISTING_BYTES)
    modified_ns = destination.stat().st_mtime_ns

    with pytest.raises(FileExistsError):
        publish_completed_file(source, destination)

    assert destination.read_bytes() == EXISTING_BYTES
    assert destination.stat().st_mtime_ns == modified_ns
    assert source.read_bytes() == MEDIA_BYTES


def test_existing_directory_and_its_contents_are_preserved(
    source: Path, destination: Path
) -> None:
    destination.mkdir()
    child = destination / 'notes.txt'
    child.write_bytes(EXISTING_BYTES)

    with pytest.raises(FileExistsError):
        publish_completed_file(source, destination)

    assert child.read_bytes() == EXISTING_BYTES
    assert source.read_bytes() == MEDIA_BYTES


def test_broken_destination_symlink_is_occupied(
    source: Path, destination: Path, tmp_path: Path
) -> None:
    target = tmp_path / 'missing-target'
    _symlink(destination, target)
    original_target = destination.readlink()

    with pytest.raises(FileExistsError):
        publish_completed_file(source, destination)

    assert destination.is_symlink()
    assert destination.readlink() == original_target
    assert not target.exists()
    assert source.read_bytes() == MEDIA_BYTES


def test_source_cannot_also_be_its_destination(source: Path) -> None:
    with pytest.raises(FileExistsError):
        publish_completed_file(source, source)

    assert source.read_bytes() == MEDIA_BYTES


def test_an_existing_hardlink_is_not_replaced(source: Path, destination: Path) -> None:
    os.link(source, destination)

    with pytest.raises(FileExistsError):
        publish_completed_file(source, destination)

    assert source.samefile(destination)
    assert source.read_bytes() == MEDIA_BYTES


def test_directory_source_is_rejected(tmp_path: Path, destination: Path) -> None:
    source = tmp_path / 'directory'
    source.mkdir()

    with pytest.raises(ValueError, match='regular file'):
        publish_completed_file(source, destination)

    assert source.is_dir()
    assert not destination.exists()


def test_symlink_source_is_rejected_without_touching_its_target(
    source: Path, destination: Path, tmp_path: Path
) -> None:
    link = tmp_path / 'source-link'
    _symlink(link, source)

    with pytest.raises(ValueError, match='regular file'):
        publish_completed_file(link, destination)

    assert link.is_symlink()
    assert source.read_bytes() == MEDIA_BYTES
    assert not destination.exists()


def test_missing_source_is_not_published(tmp_path: Path, destination: Path) -> None:
    with pytest.raises(FileNotFoundError):
        publish_completed_file(tmp_path / 'missing', destination)

    assert not destination.exists()


@pytest.mark.parametrize('invalid_source', [True, False], ids=['source', 'destination'])
def test_nul_paths_are_rejected_without_publishing_a_truncated_name(
    source: Path, destination: Path, *, invalid_source: bool
) -> None:
    attempted_source = source
    attempted_destination = destination
    if invalid_source:
        attempted_source = source.with_name(source.name + '\0ignored')
    else:
        attempted_destination = destination.with_name(destination.name + '\0ignored')

    with pytest.raises(ValueError, match='embedded null'):
        publish_completed_file(attempted_source, attempted_destination)

    assert source.read_bytes() == MEDIA_BYTES
    assert not destination.exists()


@pytest.mark.parametrize(
    'error_number', [errno.EACCES, errno.ENOSPC, errno.EXDEV, errno.EEXIST]
)
def test_native_operational_error_does_not_fall_back_to_publication(
    source: Path, destination: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    error = OSError(error_number, os.strerror(error_number))

    def fail_native(_source: Path, _destination: Path) -> None:
        raise error

    monkeypatch.setattr(media_publication, '_rename_exclusively', fail_native)

    with pytest.raises(OSError, match=re.escape(str(error))) as caught:
        publish_completed_file(source, destination)

    assert caught.value is error
    assert source.read_bytes() == MEDIA_BYTES
    assert not destination.exists()


@pytest.mark.parametrize(
    'error_number',
    sorted({errno.ENOSYS, errno.EINVAL, errno.ENOTSUP, errno.EOPNOTSUPP}),
)
def test_unsupported_native_publication_uses_link_and_leaves_source_cleanup_to_caller(
    source: Path, destination: Path, monkeypatch: pytest.MonkeyPatch, error_number: int
) -> None:
    def unsupported(_source: Path, _destination: Path) -> None:
        raise OSError(error_number, os.strerror(error_number))

    monkeypatch.setattr(media_publication, '_rename_exclusively', unsupported)

    result = publish_completed_file(source, destination)

    assert result == PublishedFile(path=destination, size=len(MEDIA_BYTES))
    assert source.read_bytes() == destination.read_bytes() == MEDIA_BYTES
    assert source.samefile(destination)
    source.unlink()
    assert destination.read_bytes() == MEDIA_BYTES


def test_failure_of_both_publication_methods_preserves_source(
    source: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unsupported(_source: Path, _destination: Path) -> None:
        raise OSError(errno.ENOSYS, 'Exclusive rename unavailable')

    def denied(*_args: object, **_kwargs: object) -> None:
        raise OSError(errno.EPERM, 'Links unavailable')

    monkeypatch.setattr(media_publication, '_rename_exclusively', unsupported)
    monkeypatch.setattr(os, 'link', denied)

    with pytest.raises(OSError, match='Links unavailable') as caught:
        publish_completed_file(source, destination)

    assert caught.value.errno == errno.EPERM
    assert source.read_bytes() == MEDIA_BYTES
    assert not destination.exists()


def test_native_publication_preserves_a_destination_created_after_initial_check(
    source: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rename = media_publication._rename_exclusively  # pyright: ignore[reportPrivateUsage]

    def another_writer_finishes(first: Path, second: Path) -> None:
        second.write_bytes(EXISTING_BYTES)
        rename(first, second)

    monkeypatch.setattr(
        media_publication, '_rename_exclusively', another_writer_finishes
    )

    with pytest.raises(FileExistsError):
        publish_completed_file(source, destination)

    assert destination.read_bytes() == EXISTING_BYTES
    assert source.read_bytes() == MEDIA_BYTES


def test_link_fallback_preserves_a_destination_created_after_initial_check(
    source: Path, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def another_writer_finishes(_source: Path, target: Path) -> None:
        target.write_bytes(EXISTING_BYTES)
        raise OSError(errno.ENOSYS, 'Exclusive rename unavailable')

    monkeypatch.setattr(
        media_publication, '_rename_exclusively', another_writer_finishes
    )

    with pytest.raises(FileExistsError):
        publish_completed_file(source, destination)

    assert destination.read_bytes() == EXISTING_BYTES
    assert source.read_bytes() == MEDIA_BYTES


def test_missing_destination_parent_is_not_created(
    source: Path, tmp_path: Path
) -> None:
    destination = tmp_path / 'missing-directory' / 'video.mp4'

    with pytest.raises(FileNotFoundError):
        publish_completed_file(source, destination)

    assert source.read_bytes() == MEDIA_BYTES
    assert not destination.parent.exists()
