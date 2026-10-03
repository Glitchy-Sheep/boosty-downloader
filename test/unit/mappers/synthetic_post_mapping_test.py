"""The synthetic post with every chunk kind maps to the domain as a whole.

The chunk-level rules have tests of their own in post_mapper_test.py. This
one checks the post-level outcome in one pass: chunk order, the signed query
on media links, the video quality choice and the unknown chunk that stays
visible instead of failing the post.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from support.synthetic_post import (
    AUDIO_ARTIST,
    AUDIO_DURATION_S,
    AUDIO_ID,
    AUDIO_NAME,
    AUDIO_SIZE,
    CDN_HOST,
    COMMENTS,
    CONTENT_COUNTS,
    FILE_ID,
    FILE_NAME,
    FILE_SIZE,
    FIRST_TEXT,
    IMAGE_HEIGHT,
    IMAGE_ID,
    IMAGE_SIZE,
    IMAGE_WIDTH,
    IMAGES_HOST,
    LIKES,
    POST_ID,
    POST_TITLE,
    SIGNED_QUERY,
    TAG_TITLES,
    TEASER_ID,
    TIER_NAME,
    TIER_PRICE,
    TIER_PRICES,
    VIDEO_DURATION_S,
    VIDEO_HOST,
    VIDEO_ID,
    VIDEO_PREVIEW,
    VIDEO_TITLE,
    synthetic_post,
)

from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.mappers.post_mapper import (
    map_post_dto_to_domain,
)
from boosty_downloader.domain.post import SubscriptionLevel
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
    assert (image.id, image.url, image.size, image.width, image.height) == (
        IMAGE_ID,
        f'{IMAGES_HOST}/image/{IMAGE_ID}{SIGNED_QUERY}',
        IMAGE_SIZE,
        IMAGE_WIDTH,
        IMAGE_HEIGHT,
    )
    assert isinstance(file, PostDataChunkFile)
    assert (file.id, file.url, file.filename, file.size) == (
        FILE_ID,
        f'{CDN_HOST}/file/{FILE_ID}{SIGNED_QUERY}',
        FILE_NAME,
        FILE_SIZE,
    )
    # Video links are signed on their own: no signed query appended.
    assert isinstance(video, PostDataChunkBoostyVideo)
    assert (
        video.id,
        video.title,
        video.quality,
        video.url,
        video.preview_url,
        video.duration,
    ) == (
        VIDEO_ID,
        VIDEO_TITLE,
        'medium',
        f'{VIDEO_HOST}/medium.mp4?fake-sig',
        VIDEO_PREVIEW,
        timedelta(seconds=VIDEO_DURATION_S),
    )
    assert isinstance(audio, PostDataChunkAudio)
    assert (
        audio.id,
        audio.url,
        audio.title,
        audio.size,
        audio.duration,
        audio.artist,
    ) == (
        AUDIO_ID,
        f'{CDN_HOST}/audio/{AUDIO_ID}{SIGNED_QUERY}',
        AUDIO_NAME,
        AUDIO_SIZE,
        timedelta(seconds=AUDIO_DURATION_S),
        AUDIO_ARTIST,
    )

    assert result.incomplete_content_types == set()
    assert result.stream_only_videos == []
    # The unknown chunk is dropped from the domain but stays visible to the reader.
    assert [u.path for u in collect_unknown_content(dto)] == ['data[10].type']


def test_what_the_listing_tells_about_the_post_maps_too():
    """Records, the locked card and the tag filter read these, not the chunks."""
    dto = PostDTO.model_validate(synthetic_post())

    post = map_post_dto_to_domain(dto, BoostyOkVideoType.medium).post

    assert post.published_at == datetime(2025, 6, 15, 15, 6, 40, tzinfo=timezone.utc)
    assert post.tags == TAG_TITLES
    # Teaser images are image chunks, signed like the others.
    assert [(image.id, image.url) for image in post.teaser] == [
        (TEASER_ID, f'{IMAGES_HOST}/teaser/{TEASER_ID}{SIGNED_QUERY}')
    ]
    assert post.content_counters == CONTENT_COUNTS
    assert (post.likes, post.comments) == (LIKES, COMMENTS)
    assert post.subscription_level == SubscriptionLevel(
        name=TIER_NAME, price=TIER_PRICE, currency_prices=TIER_PRICES
    )
    assert (post.price, post.currency_prices) == (0, {'EUR': 0, 'RUB': 0, 'USD': 0})
