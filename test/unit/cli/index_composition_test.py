"""Only writable downloads prepare an index, at the configured library-wide path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from rich.markup import escape

from boosty_downloader.cli.composition_root import (
    AppSettings,
    load_settings,
    open_app,
    resolve_cache_dir,
)
from boosty_downloader.cli.console_progress_reporter import ConsoleProgressReporter
from boosty_downloader.infrastructure.library.index import IndexStatus, LibraryIndex
from boosty_downloader.infrastructure.library.indexed_post_store import (
    IndexedJsonPostStore,
)
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.loggers.base import RichLogger


@pytest.mark.parametrize(
    ('configured_cache', 'cli_cache', 'selected_cache'),
    [
        (None, None, None),
        ('configured-cache', None, 'configured-cache'),
        (None, 'cli-cache', 'cli-cache'),
        ('configured-cache', 'cli-cache', 'cli-cache'),
    ],
)
def test_index_directory_precedence_preserves_legacy_cache_layout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    configured_cache: str | None,
    cli_cache: str | None,
    selected_cache: str | None,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / 'config.yaml'
    settings_data = {'target_directory': 'configured-library'}
    if configured_cache is not None:
        settings_data['cache_directory'] = configured_cache
    config.write_text(
        json.dumps(
            {
                'auth': {'cookie': 'session=test', 'auth_header': 'Bearer test'},
                'downloading_settings': settings_data,
            }
        ),
        encoding='utf-8',
    )
    cli_directory = Path(cli_cache) if cli_cache is not None else None

    settings = load_settings(
        username='writer',
        config_path=config,
        destination_directory=Path('selected-library'),
        cache_directory=cli_directory,
    )

    assert settings.library_root == tmp_path / 'selected-library'
    if selected_cache is None:
        assert settings.index_path is None
        assert settings.cache_dir == tmp_path / 'selected-library' / 'writer'
        legacy_cache = tmp_path / 'configured-library' / 'writer'
    else:
        assert settings.index_path == tmp_path / selected_cache / 'index.db'
        assert settings.cache_dir == tmp_path / selected_cache / 'writer'
        legacy_cache = settings.cache_dir
    assert (
        resolve_cache_dir(
            username='writer', config_path=config, cache_directory=cli_directory
        )
        == legacy_cache
    )
    assert list(tmp_path.iterdir()) == [config]


def _settings(root: Path, *, index_path: Path | None) -> AppSettings:
    return AppSettings(
        author_name='writer',
        destination_dir=root / 'writer',
        cache_dir=root / 'writer',
        auth_header='Bearer test',
        cookie='session=test',
        index_path=index_path,
    )


async def test_app_default_does_not_prepare_or_create_a_library(
    tmp_path: Path,
) -> None:
    root = tmp_path / 'library'
    cache = tmp_path / 'cache'
    settings = _settings(root, index_path=cache / 'index.db')

    async with open_app(
        settings, request_delay_seconds=0, logger=RichLogger('index-default-test')
    ) as app:
        assert isinstance(app.post_store, JsonPostStore)
        assert not root.exists()
        assert not cache.exists()

    assert not root.exists()
    assert not cache.exists()


@pytest.mark.parametrize('external_cache', [False, True])
async def test_writable_app_prepares_the_selected_index_before_returning(
    tmp_path: Path, *, external_cache: bool
) -> None:
    root = tmp_path / 'library'
    initialize_library(root)
    index_path = tmp_path / 'cache' / 'index.db' if external_cache else None
    settings = _settings(root, index_path=index_path)
    expected_path = index_path or root / '.boosty-downloader' / 'index.db'

    async with open_app(
        settings,
        request_delay_seconds=0,
        logger=RichLogger('index-writable-test'),
        update_index=True,
    ) as app:
        assert isinstance(app.post_store, IndexedJsonPostStore)
        assert expected_path.is_file()
        assert LibraryIndex(root, index_path=index_path).status() is IndexStatus.current
        assert not (root / 'writer').exists()
        if external_cache:
            assert not (root / '.boosty-downloader' / 'index.db').exists()
            assert not (expected_path.parent / 'writer').exists()


async def test_index_warning_keeps_brackets_in_paths_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'library'
    initialize_library(root)
    index_path = tmp_path / 'cache[red]' / 'index.db'
    index_path.mkdir(parents=True)
    warnings: list[str] = []

    def record_warning(_reporter: ConsoleProgressReporter, message: str) -> None:
        warnings.append(message)

    monkeypatch.setattr(ConsoleProgressReporter, 'warn', record_warning)
    async with open_app(
        _settings(root, index_path=index_path),
        request_delay_seconds=0,
        logger=RichLogger('index-warning-test'),
        update_index=True,
    ) as app:
        assert isinstance(app.post_store, IndexedJsonPostStore)

    assert len(warnings) == 1
    assert escape(str(index_path)) in warnings[0]
    assert index_path.is_dir()
