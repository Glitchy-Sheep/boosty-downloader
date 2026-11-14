"""Identical pages keep their mtime and unsafe destinations are never read."""

from __future__ import annotations

import os
from errno import EACCES, ENOSYS, EPERM
from typing import TYPE_CHECKING, TypeAlias

import pytest

from boosty_downloader.infrastructure.html_generator import renderer

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

PageComparison: TypeAlias = 'Callable[[Path, bytes], bool]'


def _write_if_changed(page: Path, content: bytes) -> bool:
    return renderer.write_html_page(page, content, only_if_changed=True)


def test_read_only_comparison_does_not_create_missing_parents(tmp_path: Path) -> None:
    page = tmp_path / 'missing' / 'post.html'

    assert not renderer.page_matches(page, b'page')
    assert not page.parent.exists()


def test_read_only_comparison_observes_exact_bytes_without_rewriting(
    tmp_path: Path,
) -> None:
    page = tmp_path / 'post.html'
    content = b'published HTML'
    page.write_bytes(content)
    timestamp = 1_700_000_000_000_000_000
    os.utime(page, ns=(timestamp, timestamp))

    assert renderer.page_matches(page, content)
    assert not renderer.page_matches(page, b'different HTML')
    assert not renderer.page_matches(page, b'longer different HTML')
    assert page.read_bytes() == content
    assert page.stat().st_mtime_ns == timestamp


def test_read_only_comparison_rejects_a_directory(tmp_path: Path) -> None:
    page = tmp_path / 'post.html'
    page.mkdir()

    with pytest.raises(ValueError, match='not a regular file'):
        renderer.page_matches(page, b'page')
    assert list(page.iterdir()) == []


def test_optional_comparison_keeps_identical_page_and_reports_changed_bytes(
    tmp_path: Path,
) -> None:
    page = tmp_path / 'post.html'
    assert renderer.render_html_to_file([], page, 'First', only_if_changed=True)
    before = page.read_bytes()
    timestamp = 1_700_000_000_000_000_000
    os.utime(page, ns=(timestamp, timestamp))

    assert not renderer.render_html_to_file([], page, 'First', only_if_changed=True)
    assert page.stat().st_mtime_ns == timestamp
    assert renderer.render_html_to_file([], page, 'Second', only_if_changed=True)
    assert page.read_bytes() != before


def test_default_writer_still_republishes_an_identical_page(tmp_path: Path) -> None:
    page = tmp_path / 'post.html'
    renderer.render_html_to_file([], page, 'Page')
    timestamp = 1_700_000_000_000_000_000
    os.utime(page, ns=(timestamp, timestamp))

    assert renderer.render_html_to_file([], page, 'Page')
    assert page.stat().st_mtime_ns != timestamp


@pytest.mark.parametrize('only_if_changed', [False, True])
def test_page_writer_rejects_directory_targets(
    tmp_path: Path, *, only_if_changed: bool
) -> None:
    page = tmp_path / 'post.html'
    page.mkdir()

    with pytest.raises(ValueError, match='not a regular file'):
        renderer.render_html_to_file([], page, 'Page', only_if_changed=only_if_changed)
    assert page.is_dir()


@pytest.mark.parametrize('compare_page', [renderer.page_matches, _write_if_changed])
def test_page_comparison_does_not_follow_a_final_link(
    tmp_path: Path, compare_page: PageComparison
) -> None:
    target = tmp_path / 'private.html'
    target.write_bytes(b'private page')
    page = tmp_path / 'post.html'
    try:
        page.symlink_to(target)
    except OSError as error:
        if (
            error.errno in {EACCES, ENOSYS, EPERM}
            or getattr(error, 'winerror', None) == 1314
        ):
            pytest.skip('Symlinks are not available')
        raise

    with pytest.raises(ValueError, match='destination is a link'):
        compare_page(page, b'private page')
    assert target.read_bytes() == b'private page'
    assert page.is_symlink()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX named pipe')
@pytest.mark.parametrize('compare_page', [renderer.page_matches, _write_if_changed])
def test_page_comparison_rejects_a_fifo_without_opening_it(
    tmp_path: Path, compare_page: PageComparison
) -> None:
    page = tmp_path / 'post.html'
    os.mkfifo(page)

    with pytest.raises(ValueError, match='not a regular file'):
        compare_page(page, b'page')


@pytest.mark.skipif(os.name == 'nt', reason='POSIX named pipe')
@pytest.mark.parametrize('compare_page', [renderer.page_matches, _write_if_changed])
def test_page_comparison_cannot_block_on_a_target_replaced_with_a_fifo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, compare_page: PageComparison
) -> None:
    page = tmp_path / 'post.html'
    renderer.render_html_to_file([], page, 'Page')
    content = page.read_bytes()
    original_open = os.open

    def replaced_open(path: Path, flags: int) -> int:
        if path == page:
            page.unlink()
            os.mkfifo(page)
        return original_open(path, flags)

    monkeypatch.setattr(renderer.os, 'open', replaced_open)

    with pytest.raises(ValueError, match='not a regular file'):
        compare_page(page, content)
