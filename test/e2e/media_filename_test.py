"""The downloader saves portable names for author files and built-in media."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, TypeAlias
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiohttp_retry import RetryClient

from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkFile,
    PostDataChunkImage,
)
from boosty_downloader.infrastructure.external_videos_downloader.external_videos_downloader import (
    ExternalVideosDownloader,
)
from boosty_downloader.infrastructure.file_downloader import (
    DownloadFileConfig,
    download_file,
)
from boosty_downloader.infrastructure.path_sanitizer import MAX_NAME_BYTES
from boosty_downloader.infrastructure.post_media_downloader import PostMediaDownloader

if TYPE_CHECKING:
    from pathlib import Path

PAYLOAD = b'synthetic media'
BuiltinMedia: TypeAlias = (
    PostDataChunkImage
    | PostDataChunkFile
    | PostDataChunkAudio
    | PostDataChunkBoostyVideo
)


@dataclass(frozen=True)
class FileDownloadCase:
    filename: str
    expected_name: str
    guess_extension: bool = False


@dataclass(frozen=True)
class MediaDownloadCase:
    chunk: BuiltinMedia
    content_type: str
    expected_path: str


def _create_media_app(content_type: str) -> web.Application:
    async def serve_payload(_: web.Request) -> web.Response:
        return web.Response(body=PAYLOAD, content_type=content_type)

    app = web.Application()
    app.router.add_get('/{tail:.*}', serve_payload)
    return app


@pytest.mark.parametrize(
    'case',
    [
        pytest.param(
            FileDownloadCase(filename='a:b?.zi?p', expected_name='ab.zip'),
            id='unsafe-extension',
        ),
        pytest.param(
            FileDownloadCase(
                filename='report.' + 'я' * 150,
                expected_name='report.' + 'я' * 115,
            ),
            id='long-extension',
        ),
        pytest.param(
            FileDownloadCase(
                filename='CON.' + 'я' * 150,
                expected_name='_CON.' + 'я' * 115,
            ),
            id='device-long-extension',
        ),
        pytest.param(
            FileDownloadCase(
                filename='lesson.v1.tar.gz', expected_name='lesson.v1.tar.gz'
            ),
            id='dotted-author-name',
        ),
        pytest.param(
            FileDownloadCase(filename='CON.txt', expected_name='_CON.txt'),
            id='device-name',
        ),
        pytest.param(
            FileDownloadCase(
                filename='я' * 300 + '.zip', expected_name='я' * 118 + '.zip'
            ),
            id='long-stem',
        ),
        pytest.param(
            FileDownloadCase(
                filename='lesson.v1',
                expected_name='lesson.v1.mp4',
                guess_extension=True,
            ),
            id='dotted-guessed-stem',
        ),
        pytest.param(
            FileDownloadCase(
                filename='C:ON', expected_name='_CON.mp4', guess_extension=True
            ),
            id='guessed-device-name',
        ),
        pytest.param(
            FileDownloadCase(
                filename='я' * 300,
                expected_name='я' * 118 + '.mp4',
                guess_extension=True,
            ),
            id='long-guessed-stem',
        ),
    ],
)
async def test_downloaded_filename_is_portable(
    tmp_path: Path, case: FileDownloadCase
) -> None:
    app = _create_media_app('video/mp4')
    async with TestServer(app) as server, RetryClient() as session:
        saved = await download_file(
            DownloadFileConfig(
                session=session,
                url=str(server.make_url('/payload')),
                filename=case.filename,
                destination=tmp_path,
                guess_extension=case.guess_extension,
            )
        )

    assert saved == tmp_path / case.expected_name
    assert saved.read_bytes() == PAYLOAD
    assert len(saved.name.encode('utf-8')) <= MAX_NAME_BYTES


async def _save_builtin_media(
    downloader: PostMediaDownloader, media: BuiltinMedia
) -> Path:
    match media:
        case PostDataChunkImage() as image:
            return await downloader.download_image(image, lambda _: None)
        case PostDataChunkFile() as file:
            return await downloader.download_file(file, lambda _: None)
        case PostDataChunkAudio() as audio:
            return await downloader.download_audio(audio, lambda _: None)
        case PostDataChunkBoostyVideo() as video:
            return await downloader.download_boosty_video(video, lambda _: None)
    pytest.fail('The fixture needs ready built-in media')


@pytest.mark.parametrize(
    'case',
    [
        pytest.param(
            MediaDownloadCase(
                chunk=PostDataChunkImage(id='image-empty-id', url='/image/'),
                content_type='image/png',
                expected_path='images/untitled.png',
            ),
            id='empty-image-url-basename',
        ),
        pytest.param(
            MediaDownloadCase(
                chunk=PostDataChunkFile(
                    id='file-empty-id', url='/file/empty', filename='/'
                ),
                content_type='application/octet-stream',
                expected_path='files/untitled',
            ),
            id='empty-file-basename',
        ),
        pytest.param(
            MediaDownloadCase(
                chunk=PostDataChunkAudio(
                    id='audio-empty-id', url='/audio/empty', title='.'
                ),
                content_type='audio/mpeg',
                expected_path='audio/untitled',
            ),
            id='empty-audio-basename',
        ),
        pytest.param(
            MediaDownloadCase(
                chunk=PostDataChunkImage(
                    id='image-api-id', url='/image/opaque%2Fpicture%3F?sig=fixture'
                ),
                content_type='image/png',
                expected_path='images/opaquepicture.png',
            ),
            id='encoded-image-name',
        ),
        pytest.param(
            MediaDownloadCase(
                chunk=PostDataChunkFile(
                    id='file-api-id', url='/file/archive', filename='nested/report.???'
                ),
                content_type='application/octet-stream',
                expected_path='files/reportuntitled',
            ),
            id='author-path-and-unsafe-extension',
        ),
        pytest.param(
            MediaDownloadCase(
                chunk=PostDataChunkAudio(
                    id='audio-api-id', url='/audio/song', title='album/track.v1.mp3'
                ),
                content_type='audio/mpeg',
                expected_path='audio/track.v1.mp3',
            ),
            id='audio-title-basename',
        ),
        pytest.param(
            MediaDownloadCase(
                chunk=PostDataChunkBoostyVideo(
                    id='abcdefgh-fixture',
                    url='/boosty_video/lesson',
                    title='я' * 300 + '.v1',
                    quality='medium',
                ),
                content_type='video/mp4',
                expected_path='boosty_videos/' + 'я' * 110 + ' (abcdefgh).mp4',
            ),
            id='long-video-title',
        ),
    ],
)
async def test_builtin_media_keeps_portable_names_and_folder_layout(
    tmp_path: Path, case: MediaDownloadCase
) -> None:
    app = _create_media_app(case.content_type)
    external = MagicMock(spec=ExternalVideosDownloader)
    async with TestServer(app) as server, RetryClient() as session:
        media = replace(case.chunk, url=str(server.make_url(case.chunk.url)))
        downloader = PostMediaDownloader(session, external, tmp_path)
        relative = await _save_builtin_media(downloader, media)

    actual = tmp_path / relative
    assert relative.as_posix() == case.expected_path
    assert actual.read_bytes() == PAYLOAD
    assert len(relative.name.encode('utf-8')) <= MAX_NAME_BYTES
    external.download_video.assert_not_called()
