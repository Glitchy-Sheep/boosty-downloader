"""Reserved names match the actual files written by the downloader."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiohttp_retry import RetryClient

from boosty_downloader.application.media_paths import (
    DiskSnapshot,
    FileMatch,
    MediaPathHint,
    find_media_file,
    reserve_media_path,
)
from boosty_downloader.infrastructure.file_downloader import (
    DownloadFileConfig,
    download_file,
)
from boosty_downloader.infrastructure.path_sanitizer import MAX_NAME_BYTES

if TYPE_CHECKING:
    from pathlib import Path

PAYLOAD = b'synthetic media'
MEDIA_ID = 'file:abcdefgh-first'


async def _serve_payload(_: web.Request) -> web.Response:
    return web.Response(body=PAYLOAD, content_type='video/mp4')


@pytest.mark.parametrize(
    ('filename', 'guess_extension'),
    [
        ('a:b?.zi?p', False),
        ('report.' + 'я' * 150, False),
        ('CON.' + 'я' * 150, False),
        ('lesson.v1.tar.gz', False),
        ('CON.txt', False),
        ('я' * 300 + '.zip', False),
        ('lesson.v1', True),
        ('C:ON', True),
        ('я' * 300, True),
    ],
    ids=[
        'unsafe-extension',
        'long-extension',
        'device-long-extension',
        'dotted-author-name',
        'device-name',
        'long-stem',
        'dotted-guessed-stem',
        'guessed-device-name',
        'long-guessed-stem',
    ],
)
async def test_reserved_candidate_is_the_downloaded_and_rediscovered_name(
    tmp_path: Path,
    filename: str,
    *,
    guess_extension: bool,
):
    preferred = filename + '.mp4' if guess_extension else filename
    reserved = reserve_media_path(preferred, MEDIA_ID, DiskSnapshot({}), {})
    app = web.Application()
    app.router.add_get('/payload', _serve_payload)

    async with TestServer(app) as server, RetryClient() as session:
        saved = await download_file(
            DownloadFileConfig(
                session=session,
                url=str(server.make_url('/payload')),
                filename=filename,
                destination=tmp_path,
                guess_extension=guess_extension,
            )
        )

    assert saved.name == reserved
    assert saved.read_bytes() == PAYLOAD
    assert len(saved.name.encode('utf-8')) <= MAX_NAME_BYTES
    assert find_media_file(
        MEDIA_ID,
        DiskSnapshot({saved.name: saved.stat().st_size}),
        {},
        preferred=MediaPathHint(filename, suffix_from_response=guess_extension),
        expected_size=len(PAYLOAD),
    ) == FileMatch(path=saved.name, size=len(PAYLOAD))
