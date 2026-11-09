"""The actual offline CLI rebuilds only the disposable index."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Literal, TypeAlias
from unittest.mock import Mock

import aiohttp
import pytest
from rich.text import Text
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from typer.testing import CliRunner

from boosty_downloader.cli import composition_root
from boosty_downloader.cli.commands import download as download_command
from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.library._index_models import IndexPost
from boosty_downloader.infrastructure.library.index import IndexStatus, LibraryIndex
from boosty_downloader.infrastructure.library.library_format import (
    LIBRARY_MARKER_PATH,
    initialize_library,
)
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.loggers.debug_file import DEBUG_LOG_FILENAME
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
POST_ID = 'abcdefgh-saved'
LOCKED_ID = 'ijklmnop-locked'
FILE_ID = 'file:example'
runner = CliRunner()
IndexCondition: TypeAlias = Literal['missing', 'corrupt', 'wrong-root', 'wrong-schema']


@dataclass(frozen=True, slots=True)
class _NodeState:
    content: bytes | None
    modified_ns: int


@dataclass(frozen=True, slots=True)
class _Library:
    root: Path
    first_folder: Path


def _snapshot(root: Path) -> dict[Path, _NodeState]:
    return {
        path.relative_to(root): _NodeState(
            path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns
        )
        for path in [root, *root.rglob('*')]
    }


def _canonical_files(root: Path) -> dict[Path, _NodeState]:
    return {
        path: state
        for path, state in _snapshot(root).items()
        if state.content is not None and not path.name.startswith('index.db')
    }


def _plain(output: str) -> str:
    return ' '.join(Text.from_ansi(output).plain.replace('│', ' ').split())


def _metadata(author: str, post_id: str) -> PostMetadata:
    return PostMetadata(
        post_id,
        author,
        f'https://boosty.to/{author}/posts/{post_id}',
        f'Saved {author}',
        NOW,
        NOW,
    )


def _save_post(root: Path, store: JsonPostStore, author: str) -> Path:
    record = StoredPost(
        _metadata(author, POST_ID),
        PostSync(NOW, NOW),
        [MediaBlock(FILE_ID)],
        {
            FILE_ID: MediaEntry(
                MediaKind.file,
                MediaStatus.downloaded,
                NOW,
                0,
                path='files/example.bin',
                size=7,
            )
        },
    )
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    directory = root / folder
    (directory / 'files').mkdir()
    (directory / 'files/example.bin').write_bytes(b'payload')
    (directory / 'post.html').write_text('Saved complete page', encoding='utf-8')
    return directory


@pytest.fixture(autouse=True)
def offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)

    async def forbidden_network(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Reindex attempted network access')

    def forbidden_auth(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Reindex attempted to load credentials')

    monkeypatch.setattr(aiohttp.ClientSession, '_request', forbidden_network)
    monkeypatch.setattr(download_command, 'notify_about_updates', forbidden_network)
    monkeypatch.setattr(composition_root, 'load_settings', forbidden_auth)
    monkeypatch.setattr(composition_root, 'init_config', forbidden_auth)


@pytest.fixture
def library(tmp_path: Path) -> _Library:
    root = tmp_path / 'library'
    initialize_library(root)
    store = JsonPostStore(root)
    first = _save_post(root, store, 'alpha')
    _save_post(root, store, 'beta')
    for author in ('alpha', 'beta'):
        store.save_author(AuthorInfo(author, NOW, title=f'Author {author}'))
    store.save_locked_post(LockedPost(_metadata('alpha', POST_ID), NOW))
    store.save_locked_post(LockedPost(_metadata('beta', LOCKED_ID), NOW))
    JsonPostMarks(root).save_marks(
        'alpha', POST_ID, PostMarks(seen_at=NOW, favorite=True)
    )
    return _Library(root, first)


def _titles(index: LibraryIndex) -> dict[str, str]:
    with index.connect() as connection:
        rows = connection.execute(
            select(IndexPost.author, IndexPost.post_id, IndexPost.title)
        ).mappings()
        return {f'{row["author"]}/{row["post_id"]}': row['title'] for row in rows}


def _prepare_index(index: LibraryIndex, condition: IndexCondition) -> None:
    if condition == 'missing':
        return
    if condition == 'corrupt':
        index.path.parent.mkdir(parents=True, exist_ok=True)
        index.path.write_bytes(b'damaged database')
        return
    index.rebuild()
    with closing(sqlite3.connect(index.path)) as database, database:
        match condition:
            case 'wrong-root':
                database.execute(
                    'UPDATE meta SET library_root = ?', ('/another-library',)
                )
            case 'wrong-schema':
                database.execute('UPDATE meta SET schema_version = 999')


@pytest.mark.parametrize(
    'condition', ['missing', 'corrupt', 'wrong-root', 'wrong-schema']
)
@pytest.mark.parametrize('external_cache', [False, True])
def test_reindex_restores_index_and_preserves_all_canonical_files(
    tmp_path: Path,
    library: _Library,
    condition: IndexCondition,
    *,
    external_cache: bool,
) -> None:
    cache = tmp_path / 'cache' if external_cache else None
    index = LibraryIndex(library.root, index_path=cache / 'index.db' if cache else None)
    _prepare_index(index, condition)
    before = _canonical_files(library.root)
    args = ['reindex', '-o', str(library.root)]
    if cache:
        args.extend(['--cache-dir', str(cache)])

    result = runner.invoke(typer_app, args)

    assert result.exit_code == 0, result.output
    assert '2 authors, 3 posts' in _plain(result.output)
    assert ''.join(str(index.path).split()) in ''.join(_plain(result.output).split())
    assert index.status() is IndexStatus.current
    assert set(_titles(index)) == {
        f'alpha/{POST_ID}',
        f'beta/{POST_ID}',
        f'beta/{LOCKED_ID}',
    }
    assert _canonical_files(library.root) == before
    assert not (tmp_path / 'config.yaml').exists()
    assert not (tmp_path / DEBUG_LOG_FILENAME).exists()
    if cache:
        assert not (library.root / '.boosty-downloader/index.db').exists()
        assert not (cache / 'alpha').exists()


@pytest.mark.parametrize('cli_cache', [False, True])
def test_reindex_reads_only_paths_and_honors_cli_cache_override(
    tmp_path: Path,
    library: _Library,
    *,
    cli_cache: bool,
) -> None:
    config = tmp_path / 'custom.yaml'
    config.write_text(
        json.dumps(
            {
                'auth': {'cookie': None, 'auth_header': []},
                'downloading_settings': {
                    'target_directory': str(library.root),
                    'cache_directory': str(tmp_path / 'configured-cache'),
                },
            }
        ),
        encoding='utf-8',
    )
    args = ['--config', str(config), 'reindex']
    expected = tmp_path / 'configured-cache' / 'index.db'
    if cli_cache:
        args.extend(['--cache-dir', str(tmp_path / 'chosen-cache')])
        expected = tmp_path / 'chosen-cache' / 'index.db'

    result = runner.invoke(typer_app, args)

    assert result.exit_code == 0, result.output
    assert (
        LibraryIndex(library.root, index_path=expected).status() is IndexStatus.current
    )
    assert not (library.root / '.boosty-downloader/index.db').exists()
    if cli_cache:
        assert not (tmp_path / 'configured-cache').exists()


def test_explicit_directories_skip_broken_config(
    tmp_path: Path, library: _Library
) -> None:
    config = tmp_path / 'config.yaml'
    config.write_text('invalid: [', encoding='utf-8')
    result = runner.invoke(
        typer_app,
        ['reindex', '-o', str(library.root), '--cache-dir', str(tmp_path / 'cache')],
    )
    assert result.exit_code == 0, result.output
    assert config.read_text(encoding='utf-8') == 'invalid: ['


def test_reindex_uses_default_library_without_creating_config_or_marker(
    tmp_path: Path,
) -> None:
    result = runner.invoke(typer_app, ['reindex'])
    root = tmp_path / 'boosty-downloads'
    assert result.exit_code == 0, result.output
    assert '0 authors, 0 posts' in _plain(result.output)
    assert (root / '.boosty-downloader/index.db').is_file()
    assert not (root / LIBRARY_MARKER_PATH).exists()
    assert not (tmp_path / 'config.yaml').exists()


@pytest.mark.parametrize('kind', ['legacy', 'bad-marker'])
@pytest.mark.parametrize('debug', [False, True])
def test_rejected_library_preserves_target_external_cache_and_debug_log(
    tmp_path: Path,
    kind: str,
    *,
    debug: bool,
) -> None:
    root = tmp_path / 'library'
    if kind == 'legacy':
        folder = root / 'writer/2024-01-02 - Saved (abc)'
        folder.mkdir(parents=True)
        (folder / 'post.html').write_bytes(b'old page')
    else:
        marker = root / LIBRARY_MARKER_PATH
        marker.parent.mkdir(parents=True)
        marker.write_text('{broken', encoding='utf-8')
    (tmp_path / DEBUG_LOG_FILENAME).write_bytes(b'previous diagnostics')
    (tmp_path / 'config.yaml').write_text('invalid: [', encoding='utf-8')
    before = _snapshot(tmp_path)
    args = ['--debug'] if debug else []
    args.extend(['reindex', '-o', str(root), '--cache-dir', str(tmp_path / 'cache')])

    result = runner.invoke(typer_app, args)

    assert result.exit_code == 1, result.output
    assert 'Cannot rebuild' not in _plain(result.output)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('source', ['post', 'viewer', 'author', 'locked'])
def test_malformed_source_fails_without_changing_previous_index_or_records(
    library: _Library,
    source: str,
) -> None:
    index = LibraryIndex(library.root)
    index.rebuild()
    before_titles = _titles(index)
    paths = {
        'post': library.first_folder / 'post.json',
        'viewer': library.first_folder / 'viewer.json',
        'author': library.root / 'alpha/.boosty-downloader/author.json',
        'locked': library.root / 'alpha/.boosty-downloader/locked.json',
    }
    paths[source].write_text('{broken', encoding='utf-8')
    before = _canonical_files(library.root)

    result = runner.invoke(typer_app, ['reindex', '-o', str(library.root)])

    assert result.exit_code == 1
    assert 'Cannot rebuild library index' in _plain(result.output)
    assert 'clean-cache' not in result.output
    assert _titles(index) == before_titles
    assert _canonical_files(library.root) == before


def test_unusable_cache_reports_literal_path_and_remedy(
    tmp_path: Path, library: _Library, caplog: pytest.LogCaptureFixture
) -> None:
    cache = tmp_path / 'cache[red]'
    index_path = cache / 'index.db'
    index_path.mkdir(parents=True)
    before = _snapshot(tmp_path)

    result = runner.invoke(
        typer_app, ['reindex', '-o', str(library.root), '--cache-dir', str(cache)]
    )

    assert result.exit_code == 1
    output = _plain(result.output)
    message = '\n'.join(record.getMessage() for record in caplog.records)
    assert 'cache[red]' in Text.from_markup(message).plain
    assert '--cache-dir' in output
    assert 'clean-cache' not in output
    assert _snapshot(tmp_path) == before


def test_sql_error_uses_reindex_failure_not_legacy_cache_hint(
    library: _Library,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failure = OperationalError('SELECT 1', {}, RuntimeError('database is locked'))
    monkeypatch.setattr(LibraryIndex, 'rebuild', Mock(side_effect=failure))
    result = runner.invoke(typer_app, ['reindex', '-o', str(library.root)])
    assert result.exit_code == 1
    assert 'Cannot rebuild library index' in _plain(result.output)
    assert 'database is locked' in _plain(result.output)
    assert 'clean-cache' not in result.output


def test_help_registers_reindex_without_author_or_writes(tmp_path: Path) -> None:
    before = _snapshot(tmp_path)
    main_help = runner.invoke(typer_app, ['--help'])
    command_help = runner.invoke(typer_app, ['--debug', 'reindex', '--help'])
    assert main_help.exit_code == command_help.exit_code == 0
    assert 'reindex' in _plain(main_help.output)
    output = _plain(command_help.output)
    assert '--cache-dir' in output
    assert '--destination-directory' in output
    assert 'Credentials are not required' in output
    assert 'USERNAME' not in output
    extra_author = runner.invoke(typer_app, ['reindex', 'writer'])
    assert extra_author.exit_code == 2
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize(
    'config_text',
    ['invalid: [', 'downloading_settings:\n  cache_directory: []\n'],
    ids=['broken-yaml', 'invalid-cache'],
)
def test_invalid_cache_configuration_fails_before_debug_or_index_writes(
    tmp_path: Path,
    library: _Library,
    config_text: str,
) -> None:
    (tmp_path / 'config.yaml').write_text(config_text, encoding='utf-8')
    (tmp_path / DEBUG_LOG_FILENAME).write_bytes(b'previous diagnostics')
    before = _snapshot(tmp_path)

    result = runner.invoke(typer_app, ['--debug', 'reindex', '-o', str(library.root)])

    assert result.exit_code == 1
    assert 'config.yaml' in _plain(result.output)
    assert _snapshot(tmp_path) == before


def test_cli_destination_overrides_config_while_using_configured_cache(
    tmp_path: Path,
    library: _Library,
) -> None:
    older_root = tmp_path / 'older'
    older_post = older_root / 'writer/2024-01-02 - Saved (abc)'
    older_post.mkdir(parents=True)
    (older_post / 'post.html').write_bytes(b'old page')
    before = _snapshot(older_root)
    cache = tmp_path / 'cache'
    (tmp_path / 'config.yaml').write_text(
        json.dumps(
            {
                'downloading_settings': {
                    'target_directory': str(older_root),
                    'cache_directory': str(cache),
                },
            }
        ),
        encoding='utf-8',
    )

    result = runner.invoke(typer_app, ['reindex', '-o', str(library.root)])

    assert result.exit_code == 0, result.output
    assert (
        LibraryIndex(library.root, index_path=cache / 'index.db').status()
        is IndexStatus.current
    )
    assert _snapshot(older_root) == before
