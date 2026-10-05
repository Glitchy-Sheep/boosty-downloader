"""Reserved names match the actual files written by the downloader."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aiohttp_retry import RetryClient

from boosty_downloader.application.mappers.live_post import LiveMedia
from boosty_downloader.application.media_paths import (
    DiskSnapshot,
    FileMatch,
    MediaPathHint,
    find_media_file,
    get_preferred_media_path,
    reserve_media_path,
)
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkFile,
    PostDataChunkImage,
)
from boosty_downloader.domain.stored_post import MediaKind
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


async def _serve_media_payload(request: web.Request) -> web.Response:
    content_types = {
        MediaKind.image.value: 'image/png',
        MediaKind.file.value: 'application/octet-stream',
        MediaKind.audio.value: 'audio/mpeg',
        MediaKind.boosty_video.value: 'video/mp4',
    }
    return web.Response(
        body=PAYLOAD, content_type=content_types[request.match_info['kind']]
    )


async def _save_builtin_media(
    downloader: PostMediaDownloader, media: LiveMedia
) -> Path:
    match media.download:
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
    'media',
    [
        pytest.param(
            LiveMedia(
                kind=MediaKind.image,
                download=PostDataChunkImage(id='image-empty-id', url='/image/'),
            ),
            id='empty-image-url-basename',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.file,
                download=PostDataChunkFile(
                    id='file-empty-id', url='/file/empty', filename='/'
                ),
            ),
            id='empty-file-basename',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.audio,
                download=PostDataChunkAudio(
                    id='audio-empty-id', url='/audio/empty', title='.'
                ),
            ),
            id='empty-audio-basename',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.image,
                download=PostDataChunkImage(
                    id='image-api-id', url='/image/opaque%2Fpicture%3F?sig=fixture'
                ),
            ),
            id='encoded-image-name',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.file,
                download=PostDataChunkFile(
                    id='file-api-id', url='/file/archive', filename='nested/report.???'
                ),
            ),
            id='author-path-and-unsafe-extension',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.audio,
                download=PostDataChunkAudio(
                    id='audio-api-id', url='/audio/song', title='album/track.v1.mp3'
                ),
            ),
            id='audio-title-basename',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.boosty_video,
                download=PostDataChunkBoostyVideo(
                    id='abcdefgh-fixture',
                    url='/boosty_video/lesson',
                    title='я' * 300 + '.v1',
                    quality='medium',
                ),
            ),
            id='long-video-title',
        ),
    ],
)
async def test_preferred_hint_finds_the_file_saved_by_post_media_downloader(
    tmp_path: Path,
    media: LiveMedia,
):
    chunk = media.download
    assert isinstance(
        chunk,
        (
            PostDataChunkImage,
            PostDataChunkFile,
            PostDataChunkAudio,
            PostDataChunkBoostyVideo,
        ),
    )
    media_id = f'{media.kind.value}:{chunk.id}'
    app = web.Application()
    app.router.add_get('/{kind}/{tail:.*}', _serve_media_payload)
    external = MagicMock(spec=ExternalVideosDownloader)

    async with TestServer(app) as server, RetryClient() as session:
        ready = replace(
            media, download=replace(chunk, url=str(server.make_url(chunk.url)))
        )
        downloader = PostMediaDownloader(session, external, tmp_path)
        relative = await _save_builtin_media(downloader, ready)

    actual = tmp_path / relative
    assert actual.read_bytes() == PAYLOAD
    assert len(relative.name.encode('utf-8')) <= MAX_NAME_BYTES
    hint = get_preferred_media_path(media_id, ready)
    assert hint is not None
    observed = relative.as_posix()
    assert find_media_file(
        media_id,
        DiskSnapshot({observed: actual.stat().st_size}),
        {},
        preferred=hint,
        expected_size=len(PAYLOAD),
    ) == FileMatch(path=observed, size=len(PAYLOAD))
    external.download_video.assert_not_called()
