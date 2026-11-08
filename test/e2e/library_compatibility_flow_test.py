"""The actual CLI protects older downloads before startup effects."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias, cast

import aiohttp
import pytest
from aiohttp.test_utils import TestServer
from e2e.download_flow_test import (
    AUTHOR,
    POST_DIR_NAME,
    _build_app,  # pyright: ignore[reportPrivateUsage]
)
from rich.text import Text
from support.synthetic_post import (
    FILE_ID,
    FILE_NAME,
    POST_ID,
    file_chunk,
    synthetic_post,
    text_chunk,
)
from typer.testing import CliRunner

from boosty_downloader.cli.commands import download as download_command
from boosty_downloader.infrastructure.boosty_api.core import client as api_client
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.loggers.debug_file import DEBUG_LOG_FILENAME
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import IO, Any

    from aiohttp.test_utils import BaseTestServer

    from boosty_downloader.infrastructure.loggers.base import RichLogger


VALID_CONFIG = 'auth:\n  cookie: "session=fake"\n  auth_header: "Bearer fake"\n'
MARKER = Path('.boosty-downloader/library.json')
FILE_BYTES = b'file bytes'
runner = CliRunner()
CommandMode: TypeAlias = Literal['bulk', 'single', 'dry-run']


@dataclass(frozen=True, slots=True)
class _NodeState:
    content: bytes | None
    modified_ns: int


def _snapshot(root: Path) -> dict[Path, _NodeState]:
    return {
        path.relative_to(root): _NodeState(
            path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns
        )
        for path in [root, *root.rglob('*')]
    }


def _plain(output: str) -> str:
    return ' '.join(Text.from_ansi(output).plain.replace('│', ' ').split())


def _assert_path_in_output(output: str, path: Path) -> None:
    assert ''.join(str(path).split()) in ''.join(_plain(output).split())


def _write_config(cwd: Path, target: Path | None = None) -> None:
    paths = ''
    if target is not None:
        paths = (
            f'downloading_settings:\n  target_directory: {json.dumps(str(target))}\n'
        )
    (cwd / 'config.yaml').write_text(VALID_CONFIG + paths, encoding='utf-8')


def _older_library(root: Path) -> Path:
    post_folder = root / 'another-author' / '2024-02-29 - Сохранённый пост (abc)'
    post_folder.mkdir(parents=True)
    (post_folder / 'post.html').write_text('Old complete page', encoding='utf-8')
    (post_folder / 'video.mp4').write_bytes(b'Old video')
    (post_folder.parent / 'post_cache.db').write_bytes(b'Old SQLite cache')
    return post_folder


def _command(root: Path | None, mode: CommandMode = 'bulk') -> list[str]:
    args = ['download', AUTHOR, '-f', 'files', '-d', '1']
    if root is not None:
        args.extend(['-o', str(root)])
    match mode:
        case 'bulk':
            pass
        case 'single':
            args.extend(['--post-url', f'https://boosty.to/{AUTHOR}/posts/{POST_ID}'])
        case 'dry-run':
            args.append('--dry-run')
    return args


def _forbid_network(monkeypatch: pytest.MonkeyPatch) -> None:
    async def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Rejected library reached network startup')

    monkeypatch.setattr(download_command, 'notify_about_updates', forbidden)
    monkeypatch.setattr(aiohttp.ClientSession, '_request', forbidden)


def _forbid_old_content_reads(monkeypatch: pytest.MonkeyPatch, folder: Path) -> None:
    original = cast('Callable[..., IO[Any]]', Path.open)
    database = folder.parent / 'post_cache.db'

    def checked_open(path: Path, *args: object, **kwargs: object) -> IO[Any]:
        assert path != database, 'Older database was opened'
        assert not path.is_relative_to(folder), 'Older post content was opened'
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', checked_open)


@pytest.mark.parametrize('mode', ['bulk', 'single', 'dry-run'])
@pytest.mark.parametrize('debug', [False, True])
def test_old_library_stops_before_config_logs_requests_and_content_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: CommandMode,
    *,
    debug: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    folder = _older_library(root)
    (tmp_path / DEBUG_LOG_FILENAME).write_text('Previous diagnostics', encoding='utf-8')
    before = _snapshot(tmp_path)
    _forbid_network(monkeypatch)
    with monkeypatch.context() as reads:
        _forbid_old_content_reads(reads, folder)
        result = runner.invoke(
            typer_app, [*(['--debug'] if debug else []), *_command(root, mode)]
        )

    assert result.exit_code == 1, result.exception
    output = _plain(result.output)
    _assert_path_in_output(result.output, root)
    assert 'another' in output.lower()
    assert 'keep' in output.lower()
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / 'config.yaml').exists()
    assert not (root / MARKER).exists()


@pytest.mark.parametrize('source', ['default', 'config', 'override'])
def test_guard_checks_the_selected_root_before_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: str
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / ('boosty-downloads' if source == 'default' else 'selected')
    _older_library(root)
    config_root = tmp_path / 'unused' if source == 'override' else root
    if source != 'default':
        (tmp_path / 'config.yaml').write_text(
            f'downloading_settings:\n  target_directory: {json.dumps(str(config_root))}\n',
            encoding='utf-8',
        )
    before = _snapshot(tmp_path)
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, _command(root if source == 'override' else None))

    assert result.exit_code == 1
    _assert_path_in_output(result.output, root)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('marker', ['{broken', '{"format_version":4}'])
def test_bad_marker_fails_before_debug_log_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, marker: str
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    path = root / MARKER
    path.parent.mkdir(parents=True)
    path.write_text(marker, encoding='utf-8')
    _write_config(tmp_path)
    (tmp_path / DEBUG_LOG_FILENAME).write_text('Previous diagnostics', encoding='utf-8')
    before = _snapshot(tmp_path)
    _forbid_network(monkeypatch)

    result = runner.invoke(typer_app, ['--debug', *_command(root)])

    assert result.exit_code == 1
    assert 'library.json' in _plain(result.output)
    assert _snapshot(tmp_path) == before


def _download_payload() -> dict[str, Any]:
    payload = synthetic_post()
    file = file_chunk()
    file['size'] = len(FILE_BYTES)
    payload['data'] = [text_chunk('Complete saved body'), file]
    return payload


def _local_network(
    monkeypatch: pytest.MonkeyPatch,
    server: BaseTestServer,
    root: Path,
    *,
    dry_run: bool = False,
) -> None:
    monkeypatch.setattr(api_client, 'BOOSTY_DEFAULT_BASE_URL', server.make_url('/v1'))

    async def check_initialized(_logger: RichLogger) -> None:
        if not dry_run:
            assert json.loads((root / MARKER).read_text()) == {'format_version': 5}

    monkeypatch.setattr(download_command, 'notify_about_updates', check_initialized)


@pytest.mark.parametrize('mode', ['bulk', 'single'])
@pytest.mark.parametrize('existing_empty', [False, True])
async def test_first_download_marks_library_and_repeated_run_keeps_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: CommandMode,
    *,
    existing_empty: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    if existing_empty:
        root.mkdir()
    old_root = tmp_path / 'older-downloads'
    _older_library(old_root)
    old_snapshot = _snapshot(old_root)
    _write_config(tmp_path, old_root)
    served: list[str] = []
    async with TestServer(_build_app(served, payload=_download_payload())) as server:
        _local_network(monkeypatch, server, root)
        first = await asyncio.to_thread(runner.invoke, typer_app, _command(root, mode))
        assert first.exit_code == 0, first.exception
        marker = _snapshot(root)[MARKER]
        second = await asyncio.to_thread(runner.invoke, typer_app, _command(root, mode))

    assert second.exit_code == 0, second.exception
    assert _snapshot(root)[MARKER] == marker
    assert _snapshot(old_root) == old_snapshot
    assert served == [f'/file/{FILE_ID}']
    saved = JsonPostStore(root).find_post(AUTHOR, POST_ID)
    assert saved is not None
    assert (root / saved.folder / 'post.html').is_file()
    assert (root / saved.folder / 'files' / FILE_NAME).read_bytes() == FILE_BYTES


@pytest.mark.parametrize('existing_empty', [False, True])
async def test_dry_run_does_not_initialize_a_new_library(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, existing_empty: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    if existing_empty:
        root.mkdir()
    _write_config(tmp_path)
    before = _snapshot(tmp_path)
    served: list[str] = []
    async with TestServer(_build_app(served, payload=_download_payload())) as server:
        _local_network(monkeypatch, server, root, dry_run=True)
        result = await asyncio.to_thread(
            runner.invoke, typer_app, ['--debug', *_command(root, 'dry-run')]
        )

    assert result.exit_code == 0, result.exception
    assert 'Download plan' in result.output
    assert _snapshot(tmp_path) == before
    assert not served


async def test_marked_recordless_post_recovers_existing_media(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    initialize_library(root)
    folder = root / AUTHOR / POST_DIR_NAME
    (folder / 'files').mkdir(parents=True)
    media = folder / 'files' / FILE_NAME
    media.write_bytes(FILE_BYTES)
    (folder / 'notes.txt').write_text('Personal notes', encoding='utf-8')
    marker = _snapshot(root)[MARKER]
    before_media = _snapshot(folder)[Path('files') / FILE_NAME]
    _write_config(tmp_path)
    served: list[str] = []
    async with TestServer(_build_app(served, payload=_download_payload())) as server:
        _local_network(monkeypatch, server, root)
        result = await asyncio.to_thread(runner.invoke, typer_app, _command(root))

    assert result.exit_code == 0, result.exception
    assert not served
    assert _snapshot(root)[MARKER] == marker
    assert _snapshot(folder)[Path('files') / FILE_NAME] == before_media
    assert (folder / 'notes.txt').read_text(encoding='utf-8') == 'Personal notes'
    saved = JsonPostStore(root).find_post(AUTHOR, POST_ID)
    assert saved is not None
    assert saved.folder == folder.relative_to(root).as_posix()
    assert saved.record is not None
    assert saved.record.media[f'file:{FILE_ID}'].size == len(FILE_BYTES)
