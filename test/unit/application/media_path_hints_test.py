"""Preferred paths follow downloader names without inventing missing metadata."""

from __future__ import annotations

from dataclasses import replace

import pytest

from boosty_downloader.application.mappers.live_post import LiveMedia
from boosty_downloader.application.media_paths import (
    MediaPathHint,
    get_preferred_media_path,
)
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
)
from boosty_downloader.domain.stored_post import MediaKind

VIDEO_ID = 'abcdefgh-fixture'
RESOURCE = 'https://cdn.example/media'


@pytest.mark.parametrize(
    ('media_id', 'media', 'expected'),
    [
        pytest.param(
            'file:fixture',
            LiveMedia(
                kind=MediaKind.file,
                filename='stale.zip',
                download=PostDataChunkFile(
                    id='fixture',
                    url=RESOURCE,
                    filename='directory/report.v1.',
                ),
            ),
            MediaPathHint(path='files/report.v1.'),
            id='author-basename-with-trailing-dot',
        ),
        pytest.param(
            'audio:fixture',
            LiveMedia(
                kind=MediaKind.audio,
                title='stale.mp3',
                download=PostDataChunkAudio(
                    id='fixture',
                    url=RESOURCE,
                    title='album/track.???',
                ),
            ),
            MediaPathHint(path='audio/track.???'),
            id='audio-basename-with-unsafe-extension',
        ),
        pytest.param(
            f'boosty_video:{VIDEO_ID}',
            LiveMedia(
                kind=MediaKind.boosty_video,
                title='Stale title',
                download=PostDataChunkBoostyVideo(
                    id=VIDEO_ID,
                    url=RESOURCE,
                    title='  Lesson.v1  ',
                    quality='medium',
                ),
            ),
            MediaPathHint(
                path='boosty_videos/Lesson.v1 (abcdefgh)', suffix_from_response=True
            ),
            id='ready-video-title',
        ),
    ],
)
def test_ready_chunk_names_take_precedence_over_descriptive_metadata(
    media_id: str,
    media: LiveMedia,
    expected: MediaPathHint,
):
    assert get_preferred_media_path(media_id, media) == expected


@pytest.mark.parametrize(
    ('url', 'expected_path'),
    [
        pytest.param(
            'https://images.example/', 'images/untitled', id='known-empty-image-name'
        ),
        pytest.param(
            'https://images.example/url-name?sig=one',
            'images/url-name',
            id='url-not-api-id',
        ),
        pytest.param(
            'https://images.example/opaque%2Fpicture%3F?sig=one',
            'images/opaquepicture',
            id='encoded-slash-is-not-a-folder',
        ),
    ],
)
def test_image_hint_uses_a_safe_url_basename_and_ignores_the_signature(
    url: str,
    expected_path: str,
):
    image = PostDataChunkImage(id='different-api-id', url=url)
    media = LiveMedia(kind=MediaKind.image, download=image)
    expected = MediaPathHint(path=expected_path, suffix_from_response=True)

    assert get_preferred_media_path('image:different-api-id', media) == expected
    refreshed = replace(
        media, download=replace(image, url=url.replace('sig=one', 'sig=two'))
    )
    assert get_preferred_media_path('image:different-api-id', refreshed) == expected


@pytest.mark.parametrize(
    ('media_id', 'ready'),
    [
        pytest.param(
            'file:fixture',
            LiveMedia(
                kind=MediaKind.file,
                filename='dir/report.???',
                download=PostDataChunkFile(
                    id='fixture',
                    url=RESOURCE,
                    filename='dir/report.???',
                ),
            ),
            id='unfinished-file',
        ),
        pytest.param(
            'audio:fixture',
            LiveMedia(
                kind=MediaKind.audio,
                title='album/song.v1.mp3',
                download=PostDataChunkAudio(
                    id='fixture',
                    url=RESOURCE,
                    title='album/song.v1.mp3',
                ),
            ),
            id='unfinished-audio',
        ),
        pytest.param(
            f'boosty_video:{VIDEO_ID}',
            LiveMedia(
                kind=MediaKind.boosty_video,
                title='я' * 300,
                download=PostDataChunkBoostyVideo(
                    id=VIDEO_ID,
                    url=RESOURCE,
                    title='я' * 300,
                    quality='medium',
                ),
            ),
            id='unfinished-long-video',
        ),
    ],
)
def test_unfinished_media_keeps_the_same_preferred_name_when_it_becomes_ready(
    media_id: str,
    ready: LiveMedia,
):
    unfinished = replace(ready, download=None)
    hint = get_preferred_media_path(media_id, ready)

    assert hint is not None
    assert get_preferred_media_path(media_id, unfinished) == hint


@pytest.mark.parametrize('title', ['', ' \t '])
def test_a_known_empty_video_title_uses_the_downloader_fallback(title: str):
    media = LiveMedia(kind=MediaKind.boosty_video, download=None, title=title)

    assert get_preferred_media_path(f'boosty_video:{VIDEO_ID}', media) == MediaPathHint(
        path='boosty_videos/video (abcdefgh)',
        suffix_from_response=True,
    )


@pytest.mark.parametrize(
    'media',
    [
        pytest.param(
            LiveMedia(kind=MediaKind.file, download=None), id='unknown-file-name'
        ),
        pytest.param(
            LiveMedia(kind=MediaKind.audio, download=None), id='unknown-audio-title'
        ),
        pytest.param(
            LiveMedia(kind=MediaKind.boosty_video, download=None),
            id='unknown-video-title',
        ),
        pytest.param(
            LiveMedia(kind=MediaKind.image, download=None), id='image-without-url'
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.external_video, download=None, title='Known title'
            ),
            id='unfinished-external',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.external_video,
                download=PostDataChunkExternalVideo(
                    url='https://video.example/watch?v=fixture'
                ),
            ),
            id='ready-external',
        ),
    ],
)
def test_missing_names_and_external_videos_have_no_preferred_path(media: LiveMedia):
    assert get_preferred_media_path(f'{media.kind.value}:fixture', media) is None


@pytest.mark.parametrize('name', ['', '.', '/'])
def test_known_empty_author_basenames_use_the_downloader_fallback(name: str):
    file = LiveMedia(kind=MediaKind.file, download=None, filename=name)
    audio = LiveMedia(kind=MediaKind.audio, download=None, title=name)

    assert get_preferred_media_path('file:fixture', file) == MediaPathHint(
        path='files/untitled'
    )
    assert get_preferred_media_path('audio:fixture', audio) == MediaPathHint(
        path='audio/untitled'
    )
