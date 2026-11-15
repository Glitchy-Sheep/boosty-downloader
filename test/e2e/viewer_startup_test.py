"""The real CLI prepares local readers and serves safe startup notices."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer
from rich.text import Text
from typer.testing import CliRunner

from boosty_downloader.cli import composition_root
from boosty_downloader.cli.commands import download as download_command
from boosty_downloader.cli.commands import view as view_command
from boosty_downloader.domain.library import PostFilters
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library.index import IndexStatus, LibraryIndex
from boosty_downloader.infrastructure.library.library_format import (
    LIBRARY_MARKER_PATH,
    initialize_library,
)
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.loggers.debug_file import DEBUG_LOG_FILENAME
from boosty_downloader.main import typer_app
from boosty_downloader.viewer.app import LIBRARY_READER
from boosty_downloader.viewer.opener import RECORD_ENV
from boosty_downloader.viewer.server import (
    ServerAddresses,
    ServerOptions,
    ViewerStartupError,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from aiohttp import web
    from typer.testing import Result

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
POST_ID = 'abcdefgh-saved'
runner = CliRunner()


@dataclass(frozen=True, slots=True)
class _StartedServer:
    app: web.Application
    options: ServerOptions


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


def _invoke(args: list[str]) -> Result:
    with patch(
        'socket.socket.connect',
        side_effect=AssertionError('Viewer contacted a remote service'),
    ):
        return runner.invoke(typer_app, args)


def _create_library(root: Path) -> Path:
    initialize_library(root)
    store = JsonPostStore(root)
    metadata = PostMetadata(
        POST_ID,
        'alpha',
        f'https://boosty.to/alpha/posts/{POST_ID}',
        root.name,
        NOW,
        NOW,
    )
    store.save_post(
        store.choose_post_folder(metadata), StoredPost(metadata, PostSync(NOW, NOW))
    )
    store.save_author(AuthorInfo('alpha', NOW, title='Saved author'))
    return root


@pytest.fixture(autouse=True)
def offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('BOOSTY_DOWNLOADER_CONFIG', raising=False)
    monkeypatch.delenv(RECORD_ENV, raising=False)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail(
            'Viewer attempted credential loading, sample config creation or an update check'
        )

    monkeypatch.setattr(composition_root, 'load_settings', forbidden)
    monkeypatch.setattr(composition_root, 'init_config', forbidden)
    monkeypatch.setattr(composition_root, 'open_app', forbidden)
    monkeypatch.setattr(download_command, 'notify_about_updates', forbidden)


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> list[_StartedServer]:
    calls: list[_StartedServer] = []

    def capture(
        app: web.Application,
        *,
        options: ServerOptions,
        on_started: Callable[[ServerAddresses], None],
    ) -> None:
        calls.append(_StartedServer(app, options))
        port = 8320
        if options.port is not None:
            port = options.port
        on_started(ServerAddresses(port=port))

    monkeypatch.setattr(view_command, 'serve', capture)
    return calls


@pytest.fixture
def library(tmp_path: Path) -> Path:
    return _create_library(tmp_path / 'library')


def _saved_folder(root: Path) -> Path:
    return next(root.glob('alpha/*/post.json')).parent.resolve()


async def test_recording_hook_is_announced_and_injected_into_file_actions(
    tmp_path: Path,
    library: Path,
    captured: list[_StartedServer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    log_path = tmp_path / 'Записи [bold], actions.jsonl'
    monkeypatch.setenv(RECORD_ENV, str(log_path))
    monkeypatch.setenv('SSH_CONNECTION', 'recording-only test')
    result = _invoke(['view', '-o', str(library), '--no-open'])
    assert result.exit_code == 0, result.output
    assert 'File actions are recorded to' in _plain(result.output)
    assert 'no files are opened.' in _plain(result.output)
    assert not log_path.exists()
    root = await asyncio.to_thread(library.resolve)
    async with TestClient(TestServer(captured[0].app)) as client:
        capabilities = await client.get('/api/opener')
        body = await capabilities.json()
        assert body['folders']
        assert body['root'] == str(root)
        response = await client.post(
            f'/api/authors/alpha/posts/{POST_ID}/open',
            json={},
            headers={'Origin': str(client.make_url('/')).rstrip('/')},
        )
        assert response.status == 204, await response.text()
    content = await asyncio.to_thread(log_path.read_text, encoding='utf-8')
    events = [json.loads(line) for line in content.splitlines()]
    folder = await asyncio.to_thread(_saved_folder, library)
    assert events == [{'action': 'open', 'path': str(folder)}]


def test_view_opens_saved_library_without_credentials_or_config(
    tmp_path: Path,
    library: Path,
    captured: list[_StartedServer],
) -> None:
    before = {
        path: state
        for path, state in _snapshot(library).items()
        if state.content is not None
    }

    result = _invoke(['view', '-o', str(library)])

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    reader = captured[0].app[LIBRARY_READER]
    assert reader is not None
    assert [author.author for author in reader.authors()] == ['alpha']
    assert [
        row.overview.post.id for row in reader.list_posts('alpha', PostFilters()).rows
    ] == [POST_ID]
    assert LibraryIndex(library).status() is IndexStatus.current
    after = _snapshot(library)
    assert {path: after[path] for path in before} == before
    assert not (tmp_path / 'config.yaml').exists()
    assert not (tmp_path / DEBUG_LOG_FILENAME).exists()
    assert captured[0].options == ServerOptions()
    assert 'http://127.0.0.1:8320/' in _plain(result.output)
    assert 'No library yet' not in result.output


@pytest.mark.parametrize(
    ('override_root', 'override_cache'),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_path_only_configuration_and_cli_overrides_select_one_index(
    tmp_path: Path,
    library: Path,
    captured: list[_StartedServer],
    *,
    override_root: bool,
    override_cache: bool,
) -> None:
    other = _create_library(tmp_path / 'chosen-library')
    configured_cache = tmp_path / 'configured-cache'
    chosen_cache = tmp_path / 'chosen-cache'
    config = tmp_path / 'paths.yaml'
    config.write_text(
        json.dumps(
            {
                'auth': {'cookie': None, 'auth_header': []},
                'downloading_settings': {
                    'target_directory': str(library),
                    'cache_directory': str(configured_cache),
                },
            }
        ),
        encoding='utf-8',
    )
    args = ['--config', str(config), 'view']
    selected_root = library
    selected_cache = configured_cache
    if override_root:
        args.extend(['-o', str(other)])
        selected_root = other
    if override_cache:
        args.extend(['--cache-dir', str(chosen_cache)])
        selected_cache = chosen_cache

    result = _invoke(args)

    assert result.exit_code == 0, result.output
    reader = captured[0].app[LIBRARY_READER]
    assert reader is not None
    post = reader.post('alpha', POST_ID)
    assert post is not None
    assert post.content.overview.post.title == selected_root.name
    assert (
        LibraryIndex(selected_root, index_path=selected_cache / 'index.db').status()
        is IndexStatus.current
    )
    assert not (selected_root / '.boosty-downloader/index.db').exists()
    assert not (selected_cache / 'alpha').exists()
    if override_cache:
        assert not configured_cache.exists()


def test_explicit_paths_skip_a_broken_configuration(
    tmp_path: Path,
    library: Path,
    captured: list[_StartedServer],
) -> None:
    config = tmp_path / 'broken.yaml'
    config.write_text('downloading_settings: [', encoding='utf-8')
    cache = tmp_path / 'cache'

    result = _invoke(
        ['--config', str(config), 'view', '-o', str(library), '--cache-dir', str(cache)]
    )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert (
        LibraryIndex(library, index_path=cache / 'index.db').status()
        is IndexStatus.current
    )


def test_config_environment_variable_selects_the_library(
    tmp_path: Path,
    library: Path,
    captured: list[_StartedServer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / 'from-environment.yaml'
    config.write_text(
        json.dumps({'downloading_settings': {'target_directory': str(library)}}),
        encoding='utf-8',
    )
    monkeypatch.setenv('BOOSTY_DOWNLOADER_CONFIG', str(config))

    result = _invoke(['view'])

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert LibraryIndex(library).status() is IndexStatus.current
    assert not (tmp_path / 'boosty-downloads').exists()


async def test_old_library_serves_explanation_before_debug_index_or_config_writes(
    tmp_path: Path,
    captured: list[_StartedServer],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _create_library(tmp_path / 'old [red] & kept')
    (root / LIBRARY_MARKER_PATH).unlink()
    config = tmp_path / 'broken.yaml'
    config.write_text('downloading_settings: [', encoding='utf-8')
    before = _snapshot(tmp_path)

    def forbidden_reader(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Incompatible libraries must not construct a reader')

    monkeypatch.setattr(view_command, 'JsonLibraryReader', forbidden_reader)
    result = _invoke(
        ['--debug', '--config', str(config), 'view', '-o', str(root), '--no-open']
    )

    assert result.exit_code == 0, result.output
    assert len(captured) == 1
    assert captured[0].app[LIBRARY_READER] is None
    assert 'Older or unmarked downloads' in _plain(result.output)
    assert '[red]' in _plain(result.output)
    async with TestClient(TestServer(captured[0].app)) as client:
        response = await client.get('/')
        body = await response.text()
    assert response.status == 200
    assert 'Older or unmarked downloads' in body
    assert 'Choose another destination directory for v5' in body
    assert 'old [red] &amp; kept' in body
    assert 'No library yet' not in body
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / DEBUG_LOG_FILENAME).exists()


async def test_empty_library_prints_download_command_and_serves_notice(
    tmp_path: Path,
    captured: list[_StartedServer],
) -> None:
    root = tmp_path / 'empty library'

    result = _invoke(['view', '-o', str(root), '--no-open'])

    assert result.exit_code == 0, result.output
    assert 'No library yet' in _plain(result.output)
    assert 'boosty-downloader download AUTHOR -o' in _plain(result.output)
    assert ''.join(str(root).split()) in ''.join(_plain(result.output).split())
    async with TestClient(TestServer(captured[0].app)) as client:
        response = await client.get('/')
        body = await response.text()
    assert response.status == 200
    assert 'No library yet' in body
    assert 'boosty-downloader download AUTHOR -o' in body
    assert not (tmp_path / 'config.yaml').exists()


def test_view_flags_reach_the_server(
    library: Path,
    captured: list[_StartedServer],
) -> None:
    result = _invoke(
        ['view', '-o', str(library), '--port', '9231', '--lan', '--no-open']
    )

    assert result.exit_code == 0, result.output
    assert captured[0].options == ServerOptions(port=9231, lan=True, open_browser=False)
    assert 'http://127.0.0.1:9231/' in _plain(result.output)


@pytest.mark.parametrize('port', ['0', '-1', '65536', 'invalid'])
def test_invalid_port_stops_before_library_or_debug_creation(
    tmp_path: Path,
    captured: list[_StartedServer],
    port: str,
) -> None:
    root = tmp_path / 'not-created'
    result = _invoke(['--debug', 'view', '-o', str(root), '--port', port])

    assert result.exit_code == 2
    assert '--port' in _plain(result.output)
    assert captured == []
    assert not root.exists()
    assert not (tmp_path / DEBUG_LOG_FILENAME).exists()


def test_corrupt_source_record_stops_before_serving(
    library: Path,
    captured: list[_StartedServer],
) -> None:
    record = next(library.glob('*/*/post.json'))
    record.write_text('{invalid', encoding='utf-8')

    result = _invoke(['view', '-o', str(library)])

    assert result.exit_code == 1
    assert captured == []
    assert 'Cannot open the library viewer' in _plain(result.output)
    assert 'Invalid post record' in _plain(result.output)
    assert 'Viewer:' not in _plain(result.output)


def test_unusable_index_reports_viewer_error_without_legacy_cache_hint(
    tmp_path: Path,
    library: Path,
    captured: list[_StartedServer],
) -> None:
    cache = tmp_path / 'cache'
    (cache / 'index.db').mkdir(parents=True)

    result = _invoke(['view', '-o', str(library), '--cache-dir', str(cache)])

    assert result.exit_code == 1
    assert captured == []
    assert 'Cannot open the library viewer' in _plain(result.output)
    assert 'clean-cache' not in result.output


def test_socket_startup_failure_exits_with_literal_diagnostic(
    library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed(*_args: object, **_kwargs: object) -> None:
        message = 'Port [red]9231[/red] is busy'
        raise ViewerStartupError(message)

    monkeypatch.setattr(view_command, 'serve', failed)
    result = _invoke(['view', '-o', str(library), '--port', '9231'])

    assert result.exit_code == 1
    assert 'Port [red]9231[/red] is busy' in _plain(result.output)
    assert 'Cannot open the library viewer' in _plain(result.output)
    assert 'Viewer:' not in _plain(result.output)


def test_help_exposes_view_options_without_starting_anything(
    tmp_path: Path,
    captured: list[_StartedServer],
) -> None:
    before = _snapshot(tmp_path)
    result = _invoke(['view', '--help'])

    assert result.exit_code == 0, result.output
    for flag in (
        '--destination-directory',
        '--cache-dir',
        '--port',
        '--lan',
        '--no-open',
    ):
        assert flag in _plain(result.output)
    assert captured == []
    assert _snapshot(tmp_path) == before
