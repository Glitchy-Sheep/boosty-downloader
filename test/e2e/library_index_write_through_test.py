"""Actual CLI downloads keep JSON durable when the disposable index fails."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest
from aiohttp.test_utils import TestServer
from e2e.author_access_flow_test import (
    _RemoteAuthor,  # pyright: ignore[reportPrivateUsage]
)
from e2e.library_compatibility_flow_test import (
    AUTHOR,
    FILE_BYTES,
    FILE_ID,
    FILE_NAME,
    POST_ID,
    _command,  # pyright: ignore[reportPrivateUsage]
    _download_payload,  # pyright: ignore[reportPrivateUsage]
    _local_network,  # pyright: ignore[reportPrivateUsage]
    _plain,  # pyright: ignore[reportPrivateUsage]
    _snapshot,  # pyright: ignore[reportPrivateUsage]
    _write_config,  # pyright: ignore[reportPrivateUsage]
)
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from typer.testing import CliRunner

from boosty_downloader.cli.commands import check as check_command
from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.domain.stored_post import MediaStatus
from boosty_downloader.infrastructure.library._index_models import IndexMedia, IndexPost
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path

    from e2e.library_compatibility_flow_test import CommandMode

    from boosty_downloader.infrastructure.library.index_projection import PostProjection
    from boosty_downloader.infrastructure.loggers.base import RichLogger

runner = CliRunner()
WARNING = 'Library index update failed'


async def _invoke(args: list[str]) -> str:
    result = await asyncio.to_thread(runner.invoke, typer_app, args)
    assert result.exit_code == 0, result.exception or result.output
    return _plain(result.output)


def _assert_saved(root: Path) -> str:
    located = JsonPostStore(root).find_post(AUTHOR, POST_ID)
    assert located is not None
    assert located.record is not None
    assert located.record.media[f'file:{FILE_ID}'].status is MediaStatus.downloaded
    folder = root / located.folder
    assert (folder / 'files' / FILE_NAME).read_bytes() == FILE_BYTES
    assert 'Complete saved body' in (folder / 'post.html').read_text(encoding='utf-8')
    return located.folder


def _indexed_access(index: LibraryIndex) -> str:
    with index.connect() as connection:
        access = connection.scalar(select(IndexPost.access))
    assert access is not None
    return access


@pytest.mark.parametrize('mode', ['bulk', 'single'])
@pytest.mark.parametrize('custom_cache', [False, True])
async def test_download_updates_index_and_preserves_marks_on_repeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: CommandMode,
    *,
    custom_cache: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    _write_config(tmp_path)
    cache = tmp_path / 'cache'
    args = _command(root, mode)
    if custom_cache:
        args.extend(['--cache-dir', str(cache)])
    index = LibraryIndex(root, index_path=cache / 'index.db' if custom_cache else None)
    remote = _RemoteAuthor(post=_download_payload())
    async with TestServer(remote.app()) as server:
        _local_network(monkeypatch, server, root)
        assert WARNING not in await _invoke(args)
        folder = _assert_saved(root)
        marks = PostMarks(seen_at=datetime.now(timezone.utc), favorite=True)
        JsonPostMarks(root).save_marks(AUTHOR, POST_ID, marks)
        saved_marks = (root / folder / 'viewer.json').read_bytes()
        assert WARNING not in await _invoke(args)

    assert (root / folder / 'viewer.json').read_bytes() == saved_marks
    assert _indexed_access(index) == 'open'
    with index.connect() as connection:
        row = connection.execute(select(IndexPost.favorite, IndexPost.seen_at)).one()
        assert row.favorite
        assert row.seen_at == marks.seen_at
        assert connection.scalar(select(IndexMedia.status)) == 'downloaded'
    if custom_cache:
        assert not (root / '.boosty-downloader' / 'index.db').exists()
        assert not (cache / AUTHOR).exists()


@pytest.mark.parametrize('mode', ['bulk', 'single'])
async def test_unusable_index_warns_once_and_download_still_saves_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: CommandMode
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    _write_config(tmp_path)
    cache = tmp_path / 'cache'
    occupied = cache / 'index.db'
    occupied.mkdir(parents=True)
    (occupied / 'notes.txt').write_text('Keep my folder', encoding='utf-8')
    before = _snapshot(cache)
    remote = _RemoteAuthor(post=_download_payload())
    async with TestServer(remote.app()) as server:
        _local_network(monkeypatch, server, root)
        output = await _invoke([*_command(root, mode), '--cache-dir', str(cache)])

    assert output.count(WARNING) == 1
    assert '--cache-dir' in output
    _assert_saved(root)
    assert _snapshot(cache) == before


async def test_index_failure_after_preparation_does_not_fail_later_json_saves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    _write_config(tmp_path)
    attempts = 0

    def fail(_self: LibraryIndex, _post: PostProjection) -> None:
        nonlocal attempts
        attempts += 1
        message = 'Index became unavailable'
        raise SQLAlchemyError(message)

    monkeypatch.setattr(LibraryIndex, 'upsert_post', fail)
    remote = _RemoteAuthor(post=_download_payload())
    async with TestServer(remote.app()) as server:
        _local_network(monkeypatch, server, root)
        output = await _invoke(_command(root))

    assert output.count(WARNING) == 1
    assert attempts == 1
    _assert_saved(root)


async def test_access_changes_update_index_without_losing_saved_body_or_marks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    _write_config(tmp_path)
    remote = _RemoteAuthor(post=_download_payload())
    index = LibraryIndex(root)
    async with TestServer(remote.app()) as server:
        _local_network(monkeypatch, server, root)
        await _invoke(_command(root))
        folder = root / _assert_saved(root)
        JsonPostMarks(root).save_marks(AUTHOR, POST_ID, PostMarks(favorite=True))
        before = _snapshot(folder)
        before_marks = (folder / 'viewer.json').read_bytes()
        remote.post.update(hasAccess=False, data=[], title='Locked title')
        await _invoke(_command(root))
        assert _indexed_access(index) == 'locked'
        assert _snapshot(folder) == before
        with index.connect() as connection:
            assert connection.scalar(select(IndexPost.title)) == 'Locked title'
            assert connection.scalar(select(IndexPost.favorite)) is True
        remote.post = _download_payload()
        await _invoke(_command(root))

    assert _indexed_access(index) == 'open'
    assert (folder / 'viewer.json').read_bytes() == before_marks
    _assert_saved(root)


@pytest.mark.parametrize('command', ['dry-run', 'check'])
async def test_read_only_commands_preserve_an_existing_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    _write_config(tmp_path)
    remote = _RemoteAuthor(post=_download_payload())

    async def no_update_check(_logger: RichLogger) -> None:
        pass

    monkeypatch.setattr(check_command, 'notify_about_updates', no_update_check)
    async with TestServer(remote.app()) as server:
        _local_network(monkeypatch, server, root)
        await _invoke(_command(root))
        before = _snapshot(tmp_path)
        args = _command(root, 'dry-run')
        if command == 'check':
            args = ['check', AUTHOR, '-o', str(root), '-d', '1']
        await _invoke(args)

    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('exclude_accessible', [False, True])
async def test_locked_only_post_becomes_saved_or_leaves_index_when_excluded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, exclude_accessible: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    _write_config(tmp_path)
    remote = _RemoteAuthor(post=_download_payload())
    remote.post.update(hasAccess=False, data=[])
    index = LibraryIndex(root)
    async with TestServer(remote.app()) as server:
        _local_network(monkeypatch, server, root)
        await _invoke(_command(root))
        assert _indexed_access(index) == 'locked'
        assert JsonPostStore(root).find_post(AUTHOR, POST_ID) is None
        with index.connect() as connection:
            assert connection.scalar(select(IndexPost.folder)) is None
        remote.post = _download_payload()
        args = _command(root)
        if exclude_accessible:
            args.extend(['--exclude-tag', 'fixture'])
        await _invoke(args)

    if exclude_accessible:
        assert JsonPostStore(root).find_post(AUTHOR, POST_ID) is None
        with index.connect() as connection:
            assert connection.scalar(select(IndexPost.post_id)) is None
    else:
        assert _indexed_access(index) == 'open'
        _assert_saved(root)


async def test_download_reports_rebuilding_a_damaged_index_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    _write_config(tmp_path)
    remote = _RemoteAuthor(post=_download_payload())
    index = LibraryIndex(root)
    async with TestServer(remote.app()) as server:
        _local_network(monkeypatch, server, root)
        await _invoke(_command(root))
        index.path.write_bytes(b'Damaged disposable index')
        output = await _invoke(_command(root))

    assert output.count('Rebuilt damaged library index') == 1
    assert WARNING not in output
    assert _indexed_access(index) == 'open'
    _assert_saved(root)
