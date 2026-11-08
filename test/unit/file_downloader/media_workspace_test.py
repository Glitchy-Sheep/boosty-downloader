"""Temporary media belongs to one download and never claims unrelated files."""

from __future__ import annotations

import errno
import logging
import os
from hashlib import sha256
from pathlib import Path

import pytest

from boosty_downloader.infrastructure import media_publication, media_workspace
from boosty_downloader.infrastructure.media_publication import publish_completed_file
from boosty_downloader.infrastructure.media_workspace import (
    cleanup_media_workspaces,
    temporary_media_workspace,
)

POST_FOLDER = 'author/post'
RELATIVE_PATH = 'files/video.mp4'
MEDIA_ID = 'file:video'
MEDIA_BYTES = b'Completed media bytes'


@pytest.fixture
def library_root(tmp_path: Path) -> Path:
    return tmp_path / 'library'


def _owner_marker(media_id: str = MEDIA_ID) -> bytes:
    digest = sha256(media_id.encode()).hexdigest()
    return f'boosty-downloader/media-output/v1\n{digest}\n'.encode()


def _stale_workspace(library_root: Path, name: str = '.boosty-crash.part') -> Path:
    directory = library_root / POST_FOLDER / 'files' / name
    directory.mkdir(parents=True)
    (directory / '.owner').write_bytes(_owner_marker())
    (directory / 'download.tmp').write_bytes(MEDIA_BYTES)
    return directory


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as error:
        if os.name == 'nt' and error.winerror == 1314:
            pytest.skip('Creating symlinks requires Windows developer mode')
        raise


def _deny_cleanup(*_args: object, **_kwargs: object) -> None:
    message = 'Workspace is still in use'
    raise PermissionError(message)


def _fail_transfer(directory: Path, failure: RuntimeError) -> None:
    (directory / 'download.tmp').write_bytes(b'Partial bytes')
    raise failure


def test_workspace_is_marked_before_writing_beside_final_destination(
    library_root: Path,
) -> None:
    with temporary_media_workspace(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    ) as workspace:
        assert workspace.destination == library_root / POST_FOLDER / RELATIVE_PATH
        assert workspace.directory.parent == workspace.destination.parent
        assert workspace.directory.name.startswith('.boosty-')
        assert workspace.directory.name.endswith('.part')
        assert (workspace.directory / '.owner').read_bytes() == _owner_marker()
        assert not workspace.destination.exists()

    assert not workspace.directory.exists()


def test_another_context_does_not_clean_an_active_workspace(library_root: Path) -> None:
    with temporary_media_workspace(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    ) as first:
        source = first.directory / 'download.tmp'
        source.write_bytes(MEDIA_BYTES)
        with temporary_media_workspace(
            library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
        ) as second:
            assert first.directory != second.directory
            assert source.read_bytes() == MEDIA_BYTES
        assert not second.directory.exists()
        assert source.read_bytes() == MEDIA_BYTES

    assert not first.directory.exists()


def test_marker_sync_failure_prevents_media_writes_and_removes_workspace(
    library_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    failure = OSError(errno.ENOSPC, 'Cannot persist workspace owner')

    def fail_sync(_descriptor: int) -> None:
        raise failure

    monkeypatch.setattr(media_workspace.os, 'fsync', fail_sync)
    with (
        pytest.raises(OSError, match='Cannot persist workspace owner') as caught,
        temporary_media_workspace(
            library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
        ),
    ):
        pytest.fail('Media writes require a durable ownership marker')

    assert caught.value is failure
    parent = library_root / POST_FOLDER / 'files'
    assert parent.is_dir()
    assert not list(parent.iterdir())


def test_body_failure_removes_partial_output(library_root: Path) -> None:
    failure = RuntimeError('Download interrupted')
    with (
        pytest.raises(RuntimeError, match='Download interrupted'),
        temporary_media_workspace(
            library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
        ) as workspace,
    ):
        _fail_transfer(workspace.directory, failure)

    parent = library_root / POST_FOLDER / 'files'
    assert not list(parent.iterdir())


@pytest.mark.parametrize('use_hardlink', [False, True], ids=['rename', 'hardlink'])
def test_publication_survives_workspace_cleanup(
    library_root: Path, monkeypatch: pytest.MonkeyPatch, *, use_hardlink: bool
) -> None:
    def unsupported(_source: Path, _destination: Path) -> None:
        raise OSError(errno.ENOSYS, 'Exclusive rename unavailable')

    if use_hardlink:
        monkeypatch.setattr(media_publication, '_rename_exclusively', unsupported)
    with temporary_media_workspace(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    ) as workspace:
        source = workspace.directory / 'download.tmp'
        source.write_bytes(MEDIA_BYTES)
        publish_completed_file(source, workspace.destination)
        if use_hardlink:
            assert source.samefile(workspace.destination)

    assert not workspace.directory.exists()
    assert workspace.destination.read_bytes() == MEDIA_BYTES


def test_fresh_cleanup_removes_owned_crash_outputs(library_root: Path) -> None:
    directory = _stale_workspace(library_root)
    nested = directory / 'fragments'
    nested.mkdir()
    (nested / 'fragment.part').write_bytes(b'Partial fragment')
    final = directory.parent / 'video.mp4'
    final.write_bytes(MEDIA_BYTES)

    cleanup_media_workspaces(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    )

    assert not directory.exists()
    assert final.read_bytes() == MEDIA_BYTES


def test_partial_cleanup_retains_ownership_for_a_later_retry(
    library_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _stale_workspace(library_root)
    second = directory / 'second.tmp'
    second.write_bytes(MEDIA_BYTES)
    outputs = {directory / 'download.tmp', second}
    removed: list[Path] = []
    unlink = Path.unlink

    def fail_second_output(path: Path, *, missing_ok: bool = False) -> None:
        if path in outputs and removed:
            message = 'Output is still in use'
            raise PermissionError(message)
        unlink(path, missing_ok=missing_ok)
        if path in outputs:
            removed.append(path)

    with monkeypatch.context() as patcher:
        patcher.setattr(Path, 'unlink', fail_second_output)
        with pytest.raises(PermissionError, match='Output is still in use'):
            cleanup_media_workspaces(
                library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
            )

    assert len(removed) == 1
    assert not removed[0].exists()
    assert (directory / '.owner').read_bytes() == _owner_marker()
    for remaining in outputs - set(removed):
        assert remaining.read_bytes() == MEDIA_BYTES

    cleanup_media_workspaces(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    )

    assert not directory.exists()


@pytest.mark.parametrize(
    'marker',
    [
        None,
        b'',
        b'unknown-owner',
        _owner_marker() + b'extra',
        b'x' * 4096,
        _owner_marker('file:another-video'),
    ],
    ids=['missing', 'empty', 'malformed', 'trailing', 'oversized', 'another-owner'],
)
def test_cleanup_preserves_unowned_directories(
    library_root: Path, marker: bytes | None
) -> None:
    directory = _stale_workspace(library_root)
    owner = directory / '.owner'
    if marker is None:
        owner.unlink()
    else:
        owner.write_bytes(marker)

    cleanup_media_workspaces(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    )

    assert (directory / 'download.tmp').read_bytes() == MEDIA_BYTES


def test_cleanup_preserves_foreign_part_files_and_unrecognized_directories(
    library_root: Path,
) -> None:
    directory = _stale_workspace(library_root, name='user-download.part')
    file = directory.parent / '.boosty-user.part'
    file.write_bytes(_owner_marker())

    cleanup_media_workspaces(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    )

    assert file.read_bytes() == _owner_marker()
    assert (directory / 'download.tmp').read_bytes() == MEDIA_BYTES


def test_cleanup_does_not_follow_workspace_symlinks(
    library_root: Path, tmp_path: Path
) -> None:
    outside = _stale_workspace(tmp_path / 'outside')
    parent = library_root / POST_FOLDER / 'files'
    parent.mkdir(parents=True)
    link = parent / '.boosty-linked.part'
    _symlink(link, outside)

    cleanup_media_workspaces(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    )

    assert link.is_symlink()
    assert (outside / 'download.tmp').read_bytes() == MEDIA_BYTES


def test_symlink_marker_does_not_claim_workspace(
    library_root: Path, tmp_path: Path
) -> None:
    directory = _stale_workspace(library_root)
    marker = directory / '.owner'
    marker.unlink()
    outside = tmp_path / 'owner'
    outside.write_bytes(_owner_marker())
    _symlink(marker, outside)

    cleanup_media_workspaces(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    )

    assert marker.is_symlink()
    assert outside.read_bytes() == _owner_marker()
    assert (directory / 'download.tmp').read_bytes() == MEDIA_BYTES


def test_cleanup_unlinks_owned_children_without_following_them(
    library_root: Path, tmp_path: Path
) -> None:
    directory = _stale_workspace(library_root)
    outside = tmp_path / 'user-files'
    outside.mkdir()
    (outside / 'keep.txt').write_bytes(MEDIA_BYTES)
    _symlink(directory / 'linked-fragments', outside)

    cleanup_media_workspaces(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    )

    assert not directory.exists()
    assert (outside / 'keep.txt').read_bytes() == MEDIA_BYTES


def test_context_preserves_a_replacement_directory(library_root: Path) -> None:
    with temporary_media_workspace(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    ) as workspace:
        moved = workspace.directory.with_name('moved-workspace')
        workspace.directory.rename(moved)
        workspace.directory.mkdir()
        (workspace.directory / '.owner').write_bytes(_owner_marker())
        replacement = workspace.directory / 'keep.txt'
        replacement.write_bytes(MEDIA_BYTES)

    assert replacement.read_bytes() == MEDIA_BYTES
    assert moved.is_dir()


def test_cleanup_failure_preserves_successful_publication_and_warns(
    library_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(media_workspace, '_remove_workspace_contents', _deny_cleanup)
    with temporary_media_workspace(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    ) as workspace:
        source = workspace.directory / 'download.tmp'
        source.write_bytes(MEDIA_BYTES)
        publish_completed_file(source, workspace.destination)

    assert workspace.destination.read_bytes() == MEDIA_BYTES
    assert workspace.directory.is_dir()
    assert any(record.levelno >= logging.WARNING for record in caplog.records)
    assert 'Workspace is still in use' in caplog.text


def test_cleanup_failure_does_not_mask_download_failure(
    library_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(media_workspace, '_remove_workspace_contents', _deny_cleanup)
    failure = RuntimeError('Download interrupted')
    with (
        pytest.raises(RuntimeError, match='Download interrupted') as caught,
        temporary_media_workspace(
            library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
        ) as workspace,
    ):
        _fail_transfer(workspace.directory, failure)

    assert caught.value is failure
    parent = library_root / POST_FOLDER / 'files'
    partials = list(parent.glob('.boosty-*.part/download.tmp'))
    assert len(partials) == 1
    assert partials[0].read_bytes() == b'Partial bytes'
    assert 'Workspace is still in use' in caplog.text


def test_explicit_cleanup_propagates_filesystem_failure(
    library_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _stale_workspace(library_root)
    monkeypatch.setattr(media_workspace, '_remove_workspace_contents', _deny_cleanup)

    with pytest.raises(PermissionError, match='Workspace is still in use'):
        cleanup_media_workspaces(
            library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
        )

    assert (directory / 'download.tmp').read_bytes() == MEDIA_BYTES


def test_cleanup_of_absent_library_does_not_create_directories(
    library_root: Path,
) -> None:
    cleanup_media_workspaces(
        library_root, POST_FOLDER, RELATIVE_PATH, media_id=MEDIA_ID
    )

    assert not library_root.exists()


def test_empty_media_id_is_rejected_before_creating_directories(
    library_root: Path,
) -> None:
    with (
        pytest.raises(ValueError, match='media'),
        temporary_media_workspace(
            library_root, POST_FOLDER, RELATIVE_PATH, media_id=''
        ),
    ):
        pytest.fail('Empty identity must not create a workspace')

    assert not library_root.exists()
