"""Published HTTP attachments retain ordinary local-file attributes."""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiohttp_retry import ExponentialRetry, RetryClient

from boosty_downloader.infrastructure.file_downloader import (
    ReservedDownloadFileConfig,
    download_reserved_file,
)
from boosty_downloader.infrastructure.media_transfer import MediaTarget

_SCRIPT_NAME: Final = 'Сценарий, local.sh'
_SCRIPT_CONTENT: Final = b'#!/bin/sh\nexit 0\n'
_EXECUTABLE_BITS: Final = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH


async def _script_response(_: web.Request) -> web.Response:
    return web.Response(body=_SCRIPT_CONTENT, content_type='application/octet-stream')


@pytest.fixture
async def downloaded_script(tmp_path: Path) -> Path:
    app = web.Application()
    app.router.add_get('/attachment', _script_response)

    def reserve(name: str) -> MediaTarget:
        return MediaTarget(tmp_path, 'writer/post', f'files/{name}', 'file:script')

    async with (
        TestServer(app) as server,
        RetryClient(retry_options=ExponentialRetry(attempts=1)) as session,
    ):
        saved = await download_reserved_file(
            ReservedDownloadFileConfig(
                session=session,
                url=str(server.make_url('/attachment')),
                filename=_SCRIPT_NAME,
                reserve=reserve,
                guess_extension=False,
            )
        )
    assert saved.path.name == _SCRIPT_NAME
    assert saved.path.read_bytes() == _SCRIPT_CONTENT
    assert saved.size == len(_SCRIPT_CONTENT)
    return saved.path


@pytest.mark.skipif(os.name != 'posix', reason='POSIX executable permission bits')
def test_downloaded_script_has_no_executable_bits(downloaded_script: Path) -> None:
    assert downloaded_script.stat().st_mode & _EXECUTABLE_BITS == 0


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS quarantine attribute')
def test_downloaded_file_has_no_macos_quarantine(downloaded_script: Path) -> None:
    result = subprocess.run(  # noqa: S603 - fixed system tool, downloaded fixture path
        ['/usr/bin/xattr', str(downloaded_script)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert 'com.apple.quarantine' not in result.stdout.splitlines()


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows Mark of the Web stream')
def test_downloaded_file_has_no_windows_zone_identifier(
    downloaded_script: Path,
) -> None:
    zone_identifier = Path(f'{downloaded_script}:Zone.Identifier')
    with pytest.raises(FileNotFoundError):
        zone_identifier.read_bytes()
