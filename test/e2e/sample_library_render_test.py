"""The generated sample is readable and renders on an independent offline copy."""

from __future__ import annotations

import hashlib
import shutil
import socket
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest
from library_sample.asset_models import AssetBackend
from library_sample.generator import prepare_sample
from library_sample.models import SampleConfig
from rich.text import Text
from typer.testing import CliRunner

from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.json_store import read_post_record
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class _FileState:
    checksum: str
    modified_ns: int


def _snapshot(root: Path, *, exclude_records: bool = False) -> dict[Path, _FileState]:
    excluded: set[str] = {'post.json', 'post.html'} if exclude_records else set()
    return {
        path.relative_to(root): _FileState(
            hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns
        )
        for path in root.rglob('*')
        if path.is_file() and path.name not in excluded
    }


def test_rendered_copy_preserves_source_sizes_and_all_user_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    original = tmp_path / 'sample'
    description = prepare_sample(
        original, SampleConfig(posts=24), backend=AssetBackend.fallback
    )
    source_before = _snapshot(original)
    copied = tmp_path / 'rendered'
    shutil.copytree(original, copied)
    protected_before = _snapshot(copied, exclude_records=True)

    def forbidden_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Offline sample rendering attempted a network connection')

    monkeypatch.setattr(socket.socket, 'connect', forbidden_network)
    result = CliRunner().invoke(typer_app, ['render', '-o', str(copied)])
    assert result.exit_code == 0, (result.output, result.exception)
    assert (
        f'Rendered {description.saved_posts} pages'
        in Text.from_ansi(result.output).plain
    )
    pages = list(copied.glob('*/*/post.html'))
    assert len(pages) == description.saved_posts
    assert _snapshot(original) == source_before
    assert _snapshot(copied, exclude_records=True) == protected_before

    actual_sizes = 0
    for page in pages:
        record = read_post_record(page.parent)
        assert record is not None
        assert record.sync.page_template == PAGE_TEMPLATE_VERSION
        assert '<html' in page.read_text(encoding='utf-8')
        for entry in record.media.values():
            if entry.status == MediaStatus.downloaded:
                assert entry.path is not None
                assert entry.size == (page.parent / entry.path).stat().st_size
                actual_sizes += 1
    assert actual_sizes > 0
