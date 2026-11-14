"""The offline CLI rebuilds downloaded pages without network or index startup."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import quote

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from e2e.download_flow_test import (
    AUTHOR,
    POST_DIR_NAME,
    _build_app,  # pyright: ignore[reportPrivateUsage]
    _QuietReporter,  # pyright: ignore[reportPrivateUsage]
    _run_download,  # pyright: ignore[reportPrivateUsage]
)
from rich.text import Text
from support.synthetic_post import POST_ID
from typer.testing import CliRunner

from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.library_format import (
    LIBRARY_MARKER_PATH,
    initialize_library,
)
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords
from boosty_downloader.infrastructure.loggers.debug_file import DEBUG_LOG_FILENAME
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
runner = CliRunner()


@dataclass(frozen=True, slots=True)
class _NodeState:
    content: bytes | None
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _Library:
    root: Path
    writer: Path
    other: Path


def _snapshot(root: Path, *, files_only: bool = False) -> dict[Path, _NodeState]:
    return {
        path.relative_to(root): _NodeState(
            path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns
        )
        for path in [root, *root.rglob('*')]
        if not files_only or path.is_file()
    }


def _plain(output: str) -> str:
    return ' '.join(Text.from_ansi(output).plain.replace('│', ' ').split())


def _assert_path_in_output(output: str, path: Path) -> None:
    assert ''.join(str(path).split()) in ''.join(_plain(output).split())


def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail(
            'Offline rendering must not open a session or connect to the network'
        )

    monkeypatch.setattr(aiohttp.ClientSession, '__init__', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)


def _save_post(root: Path, author: str) -> Path:
    record = StoredPost(
        PostMetadata(
            POST_ID,
            author,
            f'https://boosty.to/{author}/posts/{POST_ID}',
            'Saved lesson',
            NOW,
            NOW,
        ),
        PostSync(NOW, NOW, page_template=PAGE_TEMPLATE_VERSION),
        [TextBlock([PostDataChunkText.TextFragment(f'Saved text by {author}')])],
    )
    store = JsonPostRecords(root)
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    return root / folder


def _link_saved_post(root: Path, source: str, target: str) -> str:
    store = JsonPostRecords(root)
    located = store.find_post(source, POST_ID)
    assert located is not None
    assert located.record is not None
    url = f'https://boosty.to/{target}/posts/{POST_ID}?from=lesson#chapter'
    located.record.blocks.append(
        TextBlock([PostDataChunkText.TextFragment('Related lesson', link_url=url)])
    )
    store.save_post(located.folder, located.record)
    return url


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Library:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    initialize_library(root)
    return _Library(root, _save_post(root, 'writer'), _save_post(root, 'other'))


async def test_stopped_server_download_can_rebuild_missing_current_page(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'downloaded'
    initialize_library(root)
    served_media: list[str] = []
    async with TestServer(_build_app(served_media)) as server:
        reporter = _QuietReporter()
        stats = await _run_download(root, server.make_url('/'), reporter)
        assert stats.posts_downloaded == 1
        assert reporter.errors == []
    assert served_media
    JsonPostMarks(root).save_marks(
        AUTHOR, POST_ID, PostMarks(seen_at=NOW, favorite=True)
    )
    post = root / AUTHOR / POST_DIR_NAME
    original = JsonPostRecords(root).find_post(AUTHOR, POST_ID)
    assert original is not None
    assert original.record is not None
    assert original.record.sync.page_template == PAGE_TEMPLATE_VERSION
    (post / 'post.html').unlink()
    before = _snapshot(root, files_only=True)
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, ['render', '-o', str(root)])

    assert result.exit_code == 0, result.exception
    assert 'Rendered 1 page.' in _plain(result.output)
    html = (post / 'post.html').read_text(encoding='utf-8')
    assert '<title>Fixture post with every content type</title>' in html
    assert 'href="files/fixture-archive.zip"' in html
    assert 'audio/fixture-song.mp3' in html
    assert 'boosty_videos/Fixture%20video%20%2810000000%29.mp4' in html
    after = _snapshot(root, files_only=True)
    del after[(post / 'post.html').relative_to(root)]
    assert after == before
    assert not (tmp_path / 'config.yaml').exists()


@pytest.mark.parametrize('author', [None, 'writer', 'absent'])
def test_cli_selects_one_author_or_all_saved_pages(
    library: _Library,
    monkeypatch: pytest.MonkeyPatch,
    author: str | None,
) -> None:
    _forbid_network(monkeypatch)
    arguments = ['render', '-o', str(library.root)]
    if author is not None:
        arguments.append(author)

    result = runner.invoke(typer_app, arguments)

    assert result.exit_code == 0, result.exception
    expected_pages = len(
        [name for name in ('writer', 'other') if author in (None, name)]
    )
    assert f'Rendered {expected_pages} page' in _plain(result.output)
    for folder in (library.writer, library.other):
        selected = author in (None, folder.parent.name)
        assert (folder / 'post.html').exists() is selected
        if selected:
            assert f'Saved text by {folder.parent.name}' in (
                folder / 'post.html'
            ).read_text(encoding='utf-8')


def test_cross_author_links_follow_only_completed_selected_pages(
    library: _Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = _link_saved_post(library.root, 'writer', 'other')
    index = library.root / '.boosty-downloader' / 'index.db'
    index.write_bytes(b'broken disposable index')
    writer_record = (library.writer / 'post.json').read_bytes()
    _forbid_network(monkeypatch)
    arguments = ['render', 'writer', '-o', str(library.root)]

    first = runner.invoke(typer_app, arguments)

    assert first.exit_code == 0, first.exception
    assert 'Rendered 1 page.' in _plain(first.output)
    source_page = library.writer / 'post.html'
    assert f'href="{remote}"' in source_page.read_text(encoding='utf-8')
    assert not (library.other / 'post.html').exists()
    original_source = _NodeState(
        source_page.read_bytes(), source_page.stat().st_mtime_ns
    )

    target = runner.invoke(typer_app, ['render', 'other', '-o', str(library.root)])

    assert target.exit_code == 0, target.exception
    assert 'Rendered 1 page.' in _plain(target.output)
    assert _NodeState(source_page.read_bytes(), source_page.stat().st_mtime_ns) == (
        original_source
    )

    repaired = runner.invoke(typer_app, arguments)

    assert repaired.exit_code == 0, repaired.exception
    assert 'Rendered 1 page.' in _plain(repaired.output)
    relative = quote(
        f'../../{library.other.relative_to(library.root).as_posix()}/post.html'
    )
    html = source_page.read_text(encoding='utf-8')
    assert f'href="{relative}?from=lesson#chapter"' in html
    assert f'href="{remote}"' not in html
    assert (library.writer / 'post.json').read_bytes() == writer_record
    assert index.read_bytes() == b'broken disposable index'
    before = _snapshot(library.root)

    repeated = runner.invoke(typer_app, arguments)

    assert repeated.exit_code == 0, repeated.exception
    assert _snapshot(library.root) == before


def test_all_render_repairs_forward_links_and_cycles_between_authors(
    library: _Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    _link_saved_post(library.root, 'other', 'writer')
    _link_saved_post(library.root, 'writer', 'other')
    before = _snapshot(library.root, files_only=True)
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, ['render', '-o', str(library.root)])

    assert result.exit_code == 0, result.exception
    assert 'Rendered 2 pages.' in _plain(result.output)
    for source, target in (
        (library.other, library.writer),
        (library.writer, library.other),
    ):
        relative = quote(
            f'../../{target.relative_to(library.root).as_posix()}/post.html'
        )
        assert f'href="{relative}?from=lesson#chapter"' in (
            source / 'post.html'
        ).read_text(encoding='utf-8')
    after = _snapshot(library.root, files_only=True)
    for folder in (library.other, library.writer):
        del after[(folder / 'post.html').relative_to(library.root)]
    assert after == before


@pytest.mark.parametrize('source', ['missing-config', 'paths-only-config', 'override'])
def test_resolves_library_without_authentication(
    library: _Library,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    config = tmp_path / 'selected.yaml'
    arguments = ['--config', str(config), 'render']
    if source == 'paths-only-config':
        config.write_text(
            f'downloading_settings:\n  target_directory: {json.dumps(str(library.root))}\n',
            encoding='utf-8',
        )
    else:
        arguments.extend(['-o', str(library.root)])
        if source == 'override':
            config.write_text('broken: [config', encoding='utf-8')
    config_before = config.read_bytes() if config.exists() else None
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, arguments)

    assert result.exit_code == 0, result.exception
    assert 'Rendered 2 pages.' in _plain(result.output)
    assert (config.read_bytes() if config.exists() else None) == config_before
    assert not (tmp_path / 'config.yaml').exists()


@pytest.mark.parametrize('index_is_directory', [False, True])
def test_broken_index_marks_and_access_metadata_do_not_block_saved_body(
    library: _Library,
    monkeypatch: pytest.MonkeyPatch,
    *,
    index_is_directory: bool,
) -> None:
    index = library.root / '.boosty-downloader' / 'index.db'
    if index_is_directory:
        index.mkdir()
    else:
        index.write_bytes(b'not a SQLite database')
    author_metadata = library.writer.parent / '.boosty-downloader'
    author_metadata.mkdir()
    for path in (
        library.writer / 'viewer.json',
        author_metadata / 'author.json',
        author_metadata / 'locked.json',
    ):
        path.write_bytes(b'broken JSON')
    before = _snapshot(library.root, files_only=True)
    _forbid_network(monkeypatch)

    def forbidden_index(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Offline pages must not open or prepare the disposable index')

    monkeypatch.setattr(LibraryIndex, '__init__', forbidden_index)
    result = runner.invoke(typer_app, ['render', 'writer', '-o', str(library.root)])

    assert result.exit_code == 0, result.exception
    assert 'Saved text by writer' in (library.writer / 'post.html').read_text(
        encoding='utf-8'
    )
    after = _snapshot(library.root, files_only=True)
    del after[(library.writer / 'post.html').relative_to(library.root)]
    assert after == before
    assert index.is_dir() is index_is_directory


@pytest.mark.parametrize('invalid_marker', [False, True])
def test_rejected_library_with_debug_preserves_all_existing_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    invalid_marker: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'old-library'
    folder = root / 'writer' / '2024-02-29 - Old post (abcdefgh)'
    folder.mkdir(parents=True)
    (folder / 'post.html').write_bytes(b'Keep saved page')
    (folder / 'video.mp4').write_bytes(b'Keep saved media')
    (folder.parent / 'post_cache.db').write_bytes(b'Keep old cache')
    (tmp_path / DEBUG_LOG_FILENAME).write_bytes(b'Keep previous diagnostics')
    if invalid_marker:
        marker = root / LIBRARY_MARKER_PATH
        marker.parent.mkdir()
        marker.write_bytes(b'not a valid marker')
    before = _snapshot(tmp_path)
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, ['--debug', 'render', '-o', str(root)])

    assert result.exit_code == 1, result.exception
    _assert_path_in_output(result.output, root)
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / 'config.yaml').exists()


def test_invalid_author_with_debug_has_no_side_effects(
    library: _Library,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / DEBUG_LOG_FILENAME).write_bytes(b'Keep previous diagnostics')
    before = _snapshot(tmp_path)
    _forbid_network(monkeypatch)

    result = runner.invoke(
        typer_app, ['--debug', 'render', '../writer', '-o', str(library.root)]
    )

    assert result.exit_code == 2, result.exception
    assert 'AUTHOR' in _plain(result.output)
    assert _snapshot(tmp_path) == before


def test_corrupt_saved_body_exits_with_useful_error(
    library: _Library,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (library.writer / 'post.json').write_bytes(b'not JSON')
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, ['render', 'writer', '-o', str(library.root)])

    assert result.exit_code == 1, result.exception
    assert 'Cannot render saved pages' in _plain(result.output)
    _assert_path_in_output(result.output, library.writer / 'post.json')
    assert 'Rendered' not in result.output
    assert not (library.writer / 'post.html').exists()


def test_later_corrupt_record_keeps_completed_pages_without_success_summary(
    library: _Library,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (library.writer / 'post.json').write_bytes(b'not JSON')
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, ['render', '-o', str(library.root)])

    assert result.exit_code == 1, result.exception
    assert 'Cannot render saved pages' in _plain(result.output)
    assert 'Rendered' not in result.output
    _assert_path_in_output(result.output, library.writer / 'post.json')
    assert not (library.writer / 'post.html').exists()
    completed_page = (library.other / 'post.html').read_text(encoding='utf-8')
    assert '<title>Saved lesson</title>' in completed_page
    assert 'Saved text by other' in completed_page


def test_late_corrupt_record_does_not_start_link_repair(
    library: _Library, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = _link_saved_post(library.root, 'other', 'writer')
    corrupt = _save_post(library.root, 'zzz') / 'post.json'
    corrupt.write_bytes(b'not JSON')
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, ['render', '-o', str(library.root)])

    assert result.exit_code == 1, result.exception
    assert 'Cannot render saved pages' in _plain(result.output)
    assert 'Rendered' not in result.output
    _assert_path_in_output(result.output, corrupt)
    assert f'href="{remote}"' in (library.other / 'post.html').read_text(
        encoding='utf-8'
    )
    assert (library.writer / 'post.html').is_file()
    assert not corrupt.with_name('post.html').exists()


def test_empty_target_is_not_initialized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'absent-library'
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, ['render', '-o', str(root)])

    assert result.exit_code == 0, result.exception
    assert 'Rendered 0 pages.' in _plain(result.output)
    assert list(tmp_path.iterdir()) == []


def test_render_help_explains_offline_scope() -> None:
    result = runner.invoke(typer_app, ['render', '--help'])

    assert result.exit_code == 0
    output = _plain(result.output)
    assert 'AUTHOR' in output
    assert 'without network access or credentials' in output
    assert 'whole library' in output
    assert '--destination-directory' in output
