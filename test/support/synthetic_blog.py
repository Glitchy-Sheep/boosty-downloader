"""Made-up blog metadata with the structure observed on the public API."""

from typing import Any

from support.synthetic_post import (
    IMAGES_HOST,
    audio_chunk,
    block_end,
    image_chunk,
    ok_video_chunk,
    text_chunk,
)

BLOG_TITLE = 'Fixture learning journal'
OWNER_NAME = 'Example Author'
POST_COUNT = 12
DESCRIPTION_TEXT = 'Welcome to the fixture blog.'


def synthetic_blog() -> dict[str, Any]:
    """Return a fresh response with text, image, audio and video description blocks."""
    return {
        'title': BLOG_TITLE,
        'description': [
            text_chunk(DESCRIPTION_TEXT),
            block_end(),
            image_chunk(),
            audio_chunk(),
            ok_video_chunk(),
        ],
        'coverUrl': f'{IMAGES_HOST}/blog/cover.png',
        'owner': {
            'avatarUrl': f'{IMAGES_HOST}/blog/avatar.png',
            'name': OWNER_NAME,
        },
        'count': {'posts': POST_COUNT},
    }
