"""Viewer marks survive real download updates, index recovery and library moves."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from shutil import copytree
from typing import TYPE_CHECKING

import pytest
from aiohttp.test_utils import TestServer
from e2e.author_access_flow_test import (
    _RemoteAuthor,  # pyright: ignore[reportPrivateUsage]
)
from e2e.download_flow_test import AUTHOR
from e2e.library_compatibility_flow_test import (
    _local_network,  # pyright: ignore[reportPrivateUsage]
    _write_config,  # pyright: ignore[reportPrivateUsage]
)
from support.synthetic_post import POST_ID, VIDEO_ID, ok_video_chunk, text_chunk
from typer.testing import CliRunner

from boosty_downloader.domain.library import PostFilters
from boosty_downloader.domain.library_media import MediaIdentity
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader
from boosty_downloader.main import typer_app

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.domain.library import LibraryPostDetails

_VIDEO = MediaIdentity(POST_ID, f'boosty_video:{VIDEO_ID}')
_NEW_VIDEO_ID = '10000000-0000-4000-8000-000000000999'
_RUNNER = CliRunner()


@dataclass(frozen=True, slots=True)
class _MarkFile:
    content: bytes
    modified_ns: int


async def _invoke(args: list[str]) -> None:
    result = await asyncio.to_thread(_RUNNER.invoke, typer_app, args)
    assert result.exit_code == 0, result.exception or result.output


def _post(reader: JsonLibraryReader) -> LibraryPostDetails:
    result = reader.post(AUTHOR, POST_ID)
    assert result is not None
    assert result.content.record is not None
    return result


def _mark_file(root: Path, reader: JsonLibraryReader) -> _MarkFile:
    folder = _post(reader).content.folder
    assert folder is not None
    path = root / folder / 'viewer.json'
    return _MarkFile(path.read_bytes(), path.stat().st_mtime_ns)


def _mark_post(reader: JsonLibraryReader) -> None:
    assert reader.set_seen(AUTHOR, POST_ID, seen=True) is not None
    assert reader.set_favorite(AUTHOR, POST_ID, favorite=True) is not None
    result = reader.set_position(AUTHOR, _VIDEO, 12, 120)
    assert result is not None
    assert result.playback is not None
    assert result.playback.seconds == 12


async def _text_and_new_media(
    root: Path, reader: JsonLibraryReader, remote: _RemoteAuthor, args: list[str]
) -> None:
    before = _mark_file(root, reader)
    remote.post['data'][0] = text_chunk('A corrected paragraph')
    await _invoke(args)
    assert _mark_file(root, reader) == before
    assert reader.list_posts(AUTHOR, PostFilters(unseen_only=True)).total == 0

    additional = ok_video_chunk()
    additional.update(id=_NEW_VIDEO_ID, title='Additional recording')
    remote.post['data'].append(additional)
    await _invoke(args)
    assert _mark_file(root, reader) == before
    assert reader.list_posts(AUTHOR, PostFilters(unseen_only=True)).total == 1
    assert reader.set_seen(AUTHOR, POST_ID, seen=True) is not None
    assert reader.list_posts(AUTHOR, PostFilters(unseen_only=True)).total == 0


async def _removed_and_returned_media(
    root: Path, reader: JsonLibraryReader, remote: _RemoteAuthor, args: list[str]
) -> None:
    record = _post(reader).content.record
    assert record is not None
    original = deepcopy(record.media[_VIDEO.media_id])
    before = _mark_file(root, reader)
    remote.post['data'] = [
        item for item in remote.post['data'] if item.get('id') != VIDEO_ID
    ]
    await _invoke(args)
    assert _mark_file(root, reader) == before
    record = _post(reader).content.record
    assert record is not None
    assert record.media[_VIDEO.media_id].removed_at is not None
    assert reader.set_position(AUTHOR, _VIDEO, 34, 120) is not None
    before = _mark_file(root, reader)
    remote.post['data'].append(ok_video_chunk())
    await _invoke(args)
    record = _post(reader).content.record
    assert record is not None
    returned = record.media[_VIDEO.media_id]
    assert returned.removed_at is None
    assert returned.added_at == original.added_at
    assert returned.path == original.path
    assert _mark_file(root, reader) == before
    assert reader.list_posts(AUTHOR, PostFilters(unseen_only=True)).total == 0


async def _rebuild_and_move(
    root: Path, reader: JsonLibraryReader, cache: Path | None
) -> None:
    marks = reader.get_marks(AUTHOR, POST_ID)
    before = _mark_file(root, reader)
    index_path = (cache or root / '.boosty-downloader') / 'index.db'
    index_path.unlink()
    args = ['reindex', '-o', str(root)]
    if cache is not None:
        args.extend(['--cache-dir', str(cache)])
    await _invoke(args)
    assert reader.get_marks(AUTHOR, POST_ID) == marks
    assert _mark_file(root, reader) == before

    moved = root.with_name('moved-library')
    copytree(root, moved)
    moved_index = None
    if cache is not None:
        moved_cache = cache.with_name('moved-cache')
        copytree(cache, moved_cache)
        moved_index = moved_cache / 'index.db'
    restarted = JsonLibraryReader(moved, index_path=moved_index)
    restarted.prepare()
    assert restarted.get_marks(AUTHOR, POST_ID) == marks
    assert restarted.list_posts(AUTHOR, PostFilters(favorites_only=True)).total == 1
    assert restarted.list_posts(AUTHOR, PostFilters(unseen_only=True)).total == 0
    assert _mark_file(root, reader) == before


@pytest.mark.parametrize('custom_cache', [False, True])
async def test_marks_survive_download_updates_rebuild_and_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, custom_cache: bool
) -> None:
    monkeypatch.chdir(tmp_path)
    root = tmp_path / 'library'
    cache = tmp_path / 'cache' if custom_cache else None
    _write_config(tmp_path)
    args = ['download', AUTHOR, '-o', str(root), '-d', '1']
    if cache is not None:
        args.extend(['--cache-dir', str(cache)])
    reader = JsonLibraryReader(
        root, index_path=cache / 'index.db' if cache is not None else None
    )
    remote = _RemoteAuthor()
    async with TestServer(remote.app()) as server:
        _local_network(monkeypatch, server, root)
        await _invoke(args)
        reader.prepare()
        _mark_post(reader)
        await _text_and_new_media(root, reader, remote, args)
        await _removed_and_returned_media(root, reader, remote, args)
    await _rebuild_and_move(root, reader, cache)
