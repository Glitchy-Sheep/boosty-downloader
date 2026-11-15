"""Opening a post folder never redirects through a stored symlink."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from boosty_downloader.viewer.media_paths import has_post_folder, resolve_post_folder

if TYPE_CHECKING:
    from pathlib import Path


def _link(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip('Directory symlinks are unavailable')


def test_real_post_folder_resolves_without_changing_unicode_names(
    tmp_path: Path,
) -> None:
    folder = tmp_path / 'writer/2026 Имя, пост'
    folder.mkdir(parents=True)
    assert (
        resolve_post_folder(tmp_path, 'writer', 'writer/2026 Имя, пост')
        == folder.resolve()
    )
    assert has_post_folder(tmp_path, 'writer', 'writer/2026 Имя, пост')


@pytest.mark.parametrize(
    'relative',
    [
        'writer',
        'writer/',
        'writer/../outside',
        'writer/missing',
        'other/post',
        'writer/post/..',
        'writer/C:post',
        'writer/./post',
    ],
)
def test_invalid_missing_or_other_author_folder_is_unavailable(
    tmp_path: Path, relative: str
) -> None:
    (tmp_path / 'writer/post').mkdir(parents=True)
    (tmp_path / 'other/post').mkdir(parents=True)
    assert resolve_post_folder(tmp_path, 'writer', relative) is None
    assert not has_post_folder(tmp_path, 'writer', relative)


def test_regular_file_is_not_a_post_folder(tmp_path: Path) -> None:
    (tmp_path / 'writer').mkdir()
    (tmp_path / 'writer/file').write_bytes(b'data')
    assert resolve_post_folder(tmp_path, 'writer', 'writer/file') is None


def test_contained_post_folder_symlink_cannot_open(tmp_path: Path) -> None:
    target = tmp_path / 'writer/target.app'
    target.mkdir(parents=True)
    _link(tmp_path / 'writer/post', target)
    assert resolve_post_folder(tmp_path, 'writer', 'writer/post') is None
    assert not has_post_folder(tmp_path, 'writer', 'writer/post')


def test_symlink_in_post_folder_ancestor_cannot_open(tmp_path: Path) -> None:
    target = tmp_path / 'writer/actual/post'
    target.mkdir(parents=True)
    _link(tmp_path / 'writer/alias', target.parent)
    assert resolve_post_folder(tmp_path, 'writer', 'writer/alias/post') is None


def test_author_symlink_cannot_open_post(tmp_path: Path) -> None:
    target = tmp_path / 'actual/post'
    target.mkdir(parents=True)
    _link(tmp_path / 'writer', target.parent)
    assert resolve_post_folder(tmp_path, 'writer', 'writer/post') is None


def test_library_root_alias_still_resolves_real_post_folder(tmp_path: Path) -> None:
    root = tmp_path / 'library'
    target = root / 'writer/post'
    target.mkdir(parents=True)
    alias = tmp_path / 'alias'
    _link(alias, root)
    assert resolve_post_folder(alias, 'writer', 'writer/post') == target.resolve()
