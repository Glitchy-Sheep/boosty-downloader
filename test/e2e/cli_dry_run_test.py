"""The actual CLI preview observes saved posts without writing any local files."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import aiohttp
import pytest
from support.synthetic_post import (
    file_chunk,
    synthetic_post,
    text_chunk,
)
from typer.testing import CliRunner

from boosty_downloader.application.mappers.live_post import map_post_dto_to_live
from boosty_downloader.application.reconcile import prepare_record
from boosty_downloader.cli.commands import download as download_command
from boosty_downloader.infrastructure.boosty_api.core.client import BoostyAPIClient
from boosty_downloader.infrastructure.boosty_api.models.post.extra import Extra
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)
from boosty_downloader.infrastructure.boosty_api.models.post.posts_request import (
    PostsResponse,
)
from boosty_downloader.infrastructure.html_generator import PAGE_TEMPLATE_VERSION
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.loggers.debug_file import DEBUG_LOG_FILENAME
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from boosty_downloader.infrastructure.loggers.base import RichLogger

AUTHOR = 'fixture-author'
NOW = datetime(2026, 11, 8, tzinfo=timezone.utc)
VALID_CONFIG = 'auth:\n  cookie: "session=fake"\n  auth_header: "Bearer fake"\n'
runner = CliRunner()


@dataclass(frozen=True, slots=True)
class FileState:
    data: bytes | None
    modified_ns: int


def _snapshot(root: Path) -> dict[Path, FileState]:
    return {
        path.relative_to(root): FileState(
            path.read_bytes() if path.is_file() else None, path.stat().st_mtime_ns
        )
        for path in [root, *root.rglob('*')]
    }


@pytest.fixture
def post() -> PostDTO:
    payload = synthetic_post()
    payload['data'] = [text_chunk('Complete post body'), file_chunk()]
    return PostDTO.model_validate(payload)


@pytest.fixture
def listing(monkeypatch: pytest.MonkeyPatch) -> list[PostDTO]:
    posts: list[PostDTO] = []

    async def iterate(
        _self: BoostyAPIClient, author_name: str, *, posts_per_page: int
    ) -> AsyncIterator[PostsResponse]:
        assert author_name == AUTHOR
        assert posts_per_page > 0
        logging.getLogger('boosty_downloader.preview_test').debug('preview diagnostic')
        yield PostsResponse(posts=posts, extra=Extra(is_last=True, offset=''))

    async def no_update_check(logger: RichLogger) -> None:
        pass

    async def unexpected_request(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Preview attempted a media or unexpected network request')

    monkeypatch.setattr(BoostyAPIClient, 'iterate_over_posts', iterate)
    monkeypatch.setattr(download_command, 'notify_about_updates', no_update_check)
    monkeypatch.setattr(aiohttp.ClientSession, '_request', unexpected_request)
    return posts


def _write_config(root: Path) -> Path:
    path = root / 'config.yaml'
    path.write_text(VALID_CONFIG, encoding='utf-8')
    return path


def _seed_record(root: Path, post: PostDTO) -> Path:
    live = map_post_dto_to_live(post, AUTHOR, BoostyOkVideoType.medium)
    record = prepare_record(None, live, NOW)
    assert record is not None
    record.sync.page_template = PAGE_TEMPLATE_VERSION
    store = JsonPostStore(root)
    folder = root / store.choose_post_folder(record.post)
    store.save_post(folder.relative_to(root).as_posix(), record)
    (folder / 'post.html').write_text('<p>Saved complete page</p>', encoding='utf-8')
    (folder / 'viewer.json').write_text(
        '{"personal": "viewing marks"}', encoding='utf-8'
    )
    (folder / 'notes.txt').write_text('My own file', encoding='utf-8')
    return folder


def _preview_args(root: Path, *, debug: bool) -> list[str]:
    return [
        *(['--debug'] if debug else []),
        'download',
        AUTHOR,
        '--dry-run',
        '-f',
        'files',
        '--destination-directory',
        str(root / 'library'),
        '--cache-dir',
        str(root / 'custom-cache'),
    ]


@pytest.mark.parametrize('debug', [False, True])
@pytest.mark.parametrize('with_posts', [False, True])
def test_preview_keeps_an_absent_library_absent(  # noqa: PLR0913 - independent CLI modes
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    listing: list[PostDTO],
    post: PostDTO,
    *,
    debug: bool,
    with_posts: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    if with_posts:
        listing.append(post)
    before = _snapshot(tmp_path)

    result = runner.invoke(typer_app, _preview_args(tmp_path, debug=debug))

    assert result.exit_code == 0, result.exception
    assert 'Download plan' in result.output
    assert _snapshot(tmp_path) == before
    assert not (tmp_path / 'library').exists()
    assert not (tmp_path / 'custom-cache').exists()
    assert not (tmp_path / DEBUG_LOG_FILENAME).exists()
    if debug:
        assert 'preview diagnostic' in result.output


@pytest.mark.parametrize('debug', [False, True])
def test_preview_preserves_saved_records_pages_marks_and_existing_logs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    listing: list[PostDTO],
    post: PostDTO,
    *,
    debug: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    _seed_record(tmp_path / 'library', post)
    (tmp_path / DEBUG_LOG_FILENAME).write_text('Earlier diagnostics', encoding='utf-8')
    listing.append(post)
    before = _snapshot(tmp_path)

    result = runner.invoke(typer_app, _preview_args(tmp_path, debug=debug))

    assert result.exit_code == 0, result.exception
    assert 'Existing posts to update' in result.output
    assert '4.00 MB' in result.output
    assert re.search(r'Existing posts to update\s+1', result.output)
    assert re.search(r'New records\s+0', result.output)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('debug', [False, True])
def test_malformed_saved_record_does_not_get_repaired_by_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    listing: list[PostDTO],
    post: PostDTO,
    *,
    debug: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    _write_config(tmp_path)
    folder = _seed_record(tmp_path / 'library', post)
    (folder / 'post.json').write_text('{broken', encoding='utf-8')
    listing.append(post)
    before = _snapshot(tmp_path)

    result = runner.invoke(typer_app, _preview_args(tmp_path, debug=debug))

    assert result.exit_code == 1
    assert 'Cannot read saved post' in result.output
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('debug', [False, True])
@pytest.mark.parametrize('nested_config', [False, True])
def test_missing_config_preview_creates_neither_sample_nor_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    debug: bool,
    nested_config: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / ('missing/config.yaml' if nested_config else 'config.yaml')
    before = _snapshot(tmp_path)

    result = runner.invoke(
        typer_app, ['--config', str(config), *_preview_args(tmp_path, debug=debug)]
    )

    assert result.exit_code == 1
    assert 'no sample was created' in ' '.join(result.output.split())
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('debug', [False, True])
def test_single_post_preview_rejects_options_before_config_and_debug_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    debug: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    before = _snapshot(tmp_path)

    result = runner.invoke(
        typer_app,
        [
            *_preview_args(tmp_path, debug=debug),
            '--post-url',
            f'https://boosty.to/{AUTHOR}/posts/one',
        ],
    )

    assert result.exit_code == 2
    assert '--dry-run previews the full-blog run' in ' '.join(result.output.split())
    assert _snapshot(tmp_path) == before
