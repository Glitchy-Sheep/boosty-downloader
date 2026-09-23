"""The synthetic post with every chunk kind maps to the domain as a whole.

The chunk-level rules have tests of their own in post_mapper_test.py. This
one checks the post-level outcome in one pass: chunk order, the signed query
on media links, the video quality choice and the unknown chunk that stays
visible instead of failing the post.
"""

from __future__ import annotations

from datetime import datetime, timezone

from support.synthetic_post import (
    AUDIO_ID,
    AUDIO_NAME,
    AUDIO_SIZE,
    CDN_HOST,
    FILE_ID,
    FILE_NAME,
    FILE_SIZE,
    FIRST_TEXT,
    IMAGE_ID,
    IMAGE_SIZE,
    IMAGES_HOST,
    POST_ID,
    POST_TITLE,
    SIGNED_QUERY,
    VIDEO_HOST,
    VIDEO_ID,
    VIDEO_TITLE,
    synthetic_post,
)

from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.mappers.post_mapper import (
    map_post_dto_to_domain,
)
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkFile,
    PostDataChunkImage,
    PostDataChunkText,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.unknown_content import (
    collect_unknown_content,
)


def test_every_chunk_kind_maps_in_order():
    """A silent mapping change becomes wrong or missing files on disk."""
    dto = PostDTO.model_validate(synthetic_post())

    result = map_post_dto_to_domain(dto, BoostyOkVideoType.medium)

    post = result.post
    assert (post.uuid, post.title, post.signed_query) == (
        POST_ID,
        POST_TITLE,
        SIGNED_QUERY,
    )
    assert post.created_at == datetime(2025, 6, 15, 15, 6, 40, tzinfo=timezone.utc)
    assert post.has_access

    chunks = post.post_data_chunks
    assert [type(chunk) for chunk in chunks] == [
        *([PostDataChunkText] * 6),
        PostDataChunkImage,
        PostDataChunkFile,
        PostDataChunkBoostyVideo,
        PostDataChunkAudio,
    ]
    # A paragraph, then BLOCK_END as a line break, then empty blocks.
    texts = [
        [fragment.text for fragment in chunk.text_fragments]
        for chunk in chunks
        if isinstance(chunk, PostDataChunkText)
    ]
    assert texts == [[FIRST_TEXT], ['\n'], [], ['\n'], [], ['\n']]

    image, file, video, audio = chunks[6:]
    assert isinstance(image, PostDataChunkImage)
    assert (image.url, image.size) == (
        f'{IMAGES_HOST}/image/{IMAGE_ID}{SIGNED_QUERY}',
        IMAGE_SIZE,
    )
    assert isinstance(file, PostDataChunkFile)
    assert (file.url, file.filename, file.size) == (
        f'{CDN_HOST}/file/{FILE_ID}{SIGNED_QUERY}',
        FILE_NAME,
        FILE_SIZE,
    )
    # Video links are signed on their own: no signed query appended.
    assert isinstance(video, PostDataChunkBoostyVideo)
    assert (video.id, video.title, video.quality, video.url) == (
        VIDEO_ID,
        VIDEO_TITLE,
        'medium',
        f'{VIDEO_HOST}/medium.mp4?fake-sig',
    )
    assert isinstance(audio, PostDataChunkAudio)
    assert (audio.url, audio.title, audio.size) == (
        f'{CDN_HOST}/audio/{AUDIO_ID}{SIGNED_QUERY}',
        AUDIO_NAME,
        AUDIO_SIZE,
    )

    assert result.incomplete_content_types == set()
    assert result.stream_only_videos == []
    # The unknown chunk is dropped from the domain but stays visible to the reader.
    assert [u.path for u in collect_unknown_content(dto)] == ['data[10].type']
