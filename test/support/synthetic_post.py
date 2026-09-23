"""
A synthetic Boosty post for tests: every chunk kind once, nothing from the live API.

The shape follows the DTOs in boosty_api/models/post, the values are made up.
Ids follow one visible pattern, so the guard test in test/unit/synthetic_data
can tell them from real ones. Media links point at fake hosts that the e2e
server rewrites to itself.
"""

from __future__ import annotations

import json
from typing import Any

# The e2e server rewrites these to its own address.
CDN_HOST = 'https://cdn.example'
IMAGES_HOST = 'https://images.example'
VIDEO_HOST = 'https://video.example'
FAKE_HOSTS = (CDN_HOST, IMAGES_HOST, VIDEO_HOST)

# Uuid-shaped, but with a pattern no real id has.
POST_ID = '00000000-0000-4000-8000-000000000001'
IMAGE_ID = '10000000-0000-4000-8000-000000000201'
FILE_ID = '10000000-0000-4000-8000-000000000301'
VIDEO_ID = '10000000-0000-4000-8000-000000000400'
AUDIO_ID = '10000000-0000-4000-8000-000000000500'
UNKNOWN_ID = '10000000-0000-4000-8000-000000000600'

POST_TITLE = 'Fixture post with every content type'
CREATED_AT = 1_750_000_000  # 2025-06-15T15:06:40Z
UPDATED_AT = 1_750_100_000
# The listing hands out one signed query per post; media links get it appended.
SIGNED_QUERY = '?fake-signed-query'

FIRST_TEXT = 'Hello from the fixture post!'
# Whole kilobytes and megabytes: the sizes read as "10.0 KB" and "4.0 MB" on the page.
IMAGE_SIZE = 10 * 1024
FILE_NAME = 'fixture-archive.zip'
FILE_SIZE = 4 * 1024 * 1024
VIDEO_TITLE = 'Fixture video'
AUDIO_NAME = 'fixture-song.mp3'
AUDIO_SIZE = 24 * 1024
# A chunk type the client does not know: it must be reported, not fatal.
UNKNOWN_CHUNK_TYPE = 'hologram_message'

# Boosty lists every quality slot of a video and leaves most of them empty:
# only the rendered ones carry a link. The mapper picks from the filled slots.
_FILLED_QUALITIES = {
    'dash': 'dash.mpd',
    'low': 'low.mp4',
    'medium': 'medium.mp4',
    'lowest': 'lowest.mp4',
    'hls': 'hls.m3u8',
    'tiny': 'tiny.mp4',
}
_EMPTY_QUALITIES = (
    'live_cmaf',
    'live_dash',
    'dash_uni',
    'live_playback_hls',
    'ondemand_dash',
    'quad_hd',
    'high',
    'full_hd',
    'ultra_hd',
    'live_playback_dash',
    'ondemand_hls',
    'live_ondemand_hls',
)


def text_chunk(text: str) -> dict[str, Any]:
    """A text run: Boosty packs it as a JSON string of [text, style, ranges]."""
    return {
        'type': 'text',
        'content': json.dumps([text, 'unstyled', []]),
        'modificator': '',
    }


def block_end() -> dict[str, Any]:
    """The paragraph separator that follows every text block."""
    return {'type': 'text', 'content': '', 'modificator': 'BLOCK_END'}


def image_chunk() -> dict[str, Any]:
    return {
        'type': 'image',
        'id': IMAGE_ID,
        'url': f'{IMAGES_HOST}/image/{IMAGE_ID}',
        'size': IMAGE_SIZE,
        'width': 1200,
        'height': 800,
        'rendition': '',
    }


def file_chunk() -> dict[str, Any]:
    return {
        'type': 'file',
        'id': FILE_ID,
        'url': f'{CDN_HOST}/file/{FILE_ID}',
        'title': FILE_NAME,
        'size': FILE_SIZE,
        'complete': True,
    }


def ok_video_chunk() -> dict[str, Any]:
    player_urls = [
        {'type': quality, 'url': f'{VIDEO_HOST}/{name}?fake-sig'}
        for quality, name in _FILLED_QUALITIES.items()
    ]
    player_urls.extend({'type': quality, 'url': ''} for quality in _EMPTY_QUALITIES)
    return {
        'type': 'ok_video',
        'id': VIDEO_ID,
        'title': VIDEO_TITLE,
        'url': '',
        'playerUrls': player_urls,
        'duration': 120,
        'width': 640,
        'height': 480,
        'preview': f'{IMAGES_HOST}/preview/full',
        'defaultPreview': f'{IMAGES_HOST}/preview/default',
        'failoverHost': 'video-failover.example',
        'uploadStatus': 'ok',
        'status': 'ok',
        'complete': True,
        'timeCode': 0,
        'viewsCounter': 0,
        'showViewsCounter': True,
    }


def audio_chunk() -> dict[str, Any]:
    return {
        'type': 'audio_file',
        'id': AUDIO_ID,
        'url': f'{CDN_HOST}/audio/{AUDIO_ID}',
        'title': AUDIO_NAME,
        'fileType': 'MP3',
        'artist': 'Example Artist',
        'album': '',
        'track': '',
        'size': AUDIO_SIZE,
        'duration': 3,
        'complete': True,
        'uploadStatus': None,
        'timeCode': 3,
        'viewsCounter': 0,
        'showViewsCounter': True,
    }


def unknown_chunk() -> dict[str, Any]:
    return {'type': UNKNOWN_CHUNK_TYPE, 'id': UNKNOWN_ID, 'complete': True}


def synthetic_post() -> dict[str, Any]:
    """
    The post as the listing endpoint serves it, every chunk kind once.

    Three text blocks the way the editor emits them: a paragraph, then two
    empty ones, each closed by BLOCK_END. Then image, file, video, audio and
    a chunk of an unknown type. Fields the client ignores are left out, except
    a few that show the listing carries more than the models read.
    """
    return {
        'id': POST_ID,
        'intId': 101,
        'title': POST_TITLE,
        'createdAt': CREATED_AT,
        'updatedAt': UPDATED_AT,
        'publishTime': CREATED_AT,
        'hasAccess': True,
        'price': 0,
        'currencyPrices': {'EUR': 0, 'RUB': 0, 'USD': 0},
        'signedQuery': SIGNED_QUERY,
        'isPinned': False,
        'tags': [],
        'teaser': [],
        'data': [
            text_chunk(FIRST_TEXT),
            block_end(),
            text_chunk(''),
            block_end(),
            text_chunk(''),
            block_end(),
            image_chunk(),
            file_chunk(),
            ok_video_chunk(),
            audio_chunk(),
            unknown_chunk(),
        ],
    }
