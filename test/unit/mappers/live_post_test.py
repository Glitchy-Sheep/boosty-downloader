"""Complete live snapshots retain content before local reconciliation."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from support.synthetic_post import (
    AUDIO_ARTIST,
    AUDIO_DURATION_S,
    AUDIO_ID,
    AUDIO_NAME,
    AUDIO_SIZE,
    CDN_HOST,
    COMMENTS,
    CONTENT_COUNTS,
    CREATED_AT,
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
    TIER_NAME,
    TIER_PRICE,
    UPDATED_AT,
    VIDEO_DURATION_S,
    VIDEO_HOST,
    VIDEO_ID,
    VIDEO_PREVIEW,
    VIDEO_TITLE,
    audio_chunk,
    block_end,
    file_chunk,
    image_chunk,
    ok_video_chunk,
    synthetic_post,
    text_chunk,
)

from boosty_downloader.application.filtering import BoostyOkVideoType
from boosty_downloader.application.mappers.live_post import (
    LivePost,
    map_post_dto_to_live,
)
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkExternalVideo,
    PostDataChunkFile,
    PostDataChunkImage,
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.domain.stored_post import (
    LineBreak,
    ListBlock,
    ListItem,
    MediaBlock,
    MediaKind,
    ParagraphBreak,
    PostMetadata,
    TextBlock,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO

AUTHOR = 'fixture-author'
EXTERNAL_URL = 'https://video.example/watch?v=lesson&part=2'
TextFragment = PostDataChunkText.TextFragment
TextStyle = TextFragment.TextStyle


def _map_payload(payload: dict[str, object]) -> LivePost:
    return map_post_dto_to_live(
        PostDTO.model_validate(payload), AUTHOR, BoostyOkVideoType.medium
    )


def _map_chunks(chunks: list[dict[str, object]]) -> LivePost:
    return _map_payload({**synthetic_post(), 'data': chunks})


def test_complete_post_keeps_metadata_body_order_and_blank_paragraphs():
    live = _map_payload(synthetic_post())

    assert live.has_access
    assert live.post == PostMetadata(
        id=POST_ID,
        author=AUTHOR,
        url=f'https://boosty.to/{AUTHOR}/posts/{POST_ID}',
        title=POST_TITLE,
        created_at=datetime.fromtimestamp(CREATED_AT, timezone.utc),
        updated_at=datetime.fromtimestamp(UPDATED_AT, timezone.utc),
        published_at=datetime.fromtimestamp(CREATED_AT, timezone.utc),
        tags=TAG_TITLES,
        tier=TIER_NAME,
        tier_price_rub=TIER_PRICE,
        post_price_rub=0,
        likes=LIKES,
        comments=COMMENTS,
        content_counters=CONTENT_COUNTS,
    )
    assert live.blocks == [
        TextBlock([TextFragment(FIRST_TEXT)]),
        ParagraphBreak(),
        TextBlock([]),
        ParagraphBreak(),
        TextBlock([]),
        ParagraphBreak(),
        MediaBlock(f'image:{IMAGE_ID}'),
        MediaBlock(f'file:{FILE_ID}'),
        MediaBlock(f'boosty_video:{VIDEO_ID}'),
        MediaBlock(f'audio:{AUDIO_ID}'),
    ]
    assert len(live.media) == 4


def test_downloadable_media_retains_details_and_signed_urls():
    live = _map_payload(synthetic_post())
    image = live.media[f'image:{IMAGE_ID}']
    file = live.media[f'file:{FILE_ID}']
    video = live.media[f'boosty_video:{VIDEO_ID}']
    audio = live.media[f'audio:{AUDIO_ID}']

    assert image.kind is MediaKind.image
    assert (image.expected_size, image.width, image.height) == (
        IMAGE_SIZE,
        IMAGE_WIDTH,
        IMAGE_HEIGHT,
    )
    assert image.download == PostDataChunkImage(
        id=IMAGE_ID,
        url=f'{IMAGES_HOST}/image/{IMAGE_ID}{SIGNED_QUERY}',
        size=IMAGE_SIZE,
        width=IMAGE_WIDTH,
        height=IMAGE_HEIGHT,
    )
    assert file.kind is MediaKind.file
    assert (file.filename, file.expected_size) == (FILE_NAME, FILE_SIZE)
    assert file.download == PostDataChunkFile(
        id=FILE_ID,
        url=f'{CDN_HOST}/file/{FILE_ID}{SIGNED_QUERY}',
        filename=FILE_NAME,
        size=FILE_SIZE,
    )
    assert video.kind is MediaKind.boosty_video
    assert (video.title, video.duration, video.preview_url) == (
        VIDEO_TITLE,
        timedelta(seconds=VIDEO_DURATION_S),
        VIDEO_PREVIEW,
    )
    assert video.download == PostDataChunkBoostyVideo(
        id=VIDEO_ID,
        title=VIDEO_TITLE,
        url=f'{VIDEO_HOST}/medium.mp4?fake-sig',
        quality='medium',
        preview_url=VIDEO_PREVIEW,
        duration=timedelta(seconds=VIDEO_DURATION_S),
    )
    assert audio.kind is MediaKind.audio
    assert (audio.title, audio.artist, audio.duration, audio.expected_size) == (
        AUDIO_NAME,
        AUDIO_ARTIST,
        timedelta(seconds=AUDIO_DURATION_S),
        AUDIO_SIZE,
    )
    assert audio.download == PostDataChunkAudio(
        id=AUDIO_ID,
        url=f'{CDN_HOST}/audio/{AUDIO_ID}{SIGNED_QUERY}',
        title=AUDIO_NAME,
        size=AUDIO_SIZE,
        duration=timedelta(seconds=AUDIO_DURATION_S),
        artist=AUDIO_ARTIST,
    )


def test_unfinished_uploads_keep_their_place_and_identity_when_they_become_ready():
    payload = synthetic_post()
    payload['data'] = [
        text_chunk('Before uploads'),
        {**ok_video_chunk(), 'complete': False},
        image_chunk(),
        {**file_chunk(), 'complete': False},
        {**audio_chunk(), 'complete': False},
    ]
    before = _map_payload(payload)
    assert before.blocks == [
        TextBlock([TextFragment('Before uploads')]),
        MediaBlock(f'boosty_video:{VIDEO_ID}'),
        MediaBlock(f'image:{IMAGE_ID}'),
        MediaBlock(f'file:{FILE_ID}'),
        MediaBlock(f'audio:{AUDIO_ID}'),
    ]
    for media_id in (
        f'boosty_video:{VIDEO_ID}',
        f'file:{FILE_ID}',
        f'audio:{AUDIO_ID}',
    ):
        assert before.media[media_id].download is None
    assert before.media[f'boosty_video:{VIDEO_ID}'].preview_url == VIDEO_PREVIEW
    assert before.media[f'file:{FILE_ID}'].filename == FILE_NAME
    assert before.media[f'audio:{AUDIO_ID}'].artist == AUDIO_ARTIST

    for chunk in payload['data']:
        if 'complete' in chunk:
            chunk['complete'] = True
    payload['signedQuery'] = '?next-run'
    after = _map_payload(payload)
    assert after.blocks == before.blocks
    assert after.media.keys() == before.media.keys()
    assert all(media.download is not None for media in after.media.values())
    image = after.media[f'image:{IMAGE_ID}'].download
    assert isinstance(image, PostDataChunkImage)
    assert image.url.endswith('?next-run')
    assert after.post.updated_at == before.post.updated_at


@pytest.mark.parametrize(
    'urls',
    [
        [{'type': 'hls', 'url': 'https://video.example/stream.m3u8'}],
        [{'type': 'hls', 'url': ''}, {'type': 'medium', 'url': ''}],
    ],
    ids=['stream-only', 'empty-urls'],
)
def test_complete_video_without_a_progressive_url_stays_in_the_body(
    urls: list[dict[str, str]],
):
    live = _map_chunks([{**ok_video_chunk(), 'playerUrls': urls}])

    assert live.blocks == [MediaBlock(f'boosty_video:{VIDEO_ID}')]
    video = live.media[f'boosty_video:{VIDEO_ID}']
    assert video.download is None
    assert (video.title, video.preview_url, video.duration) == (
        VIDEO_TITLE,
        VIDEO_PREVIEW,
        timedelta(seconds=VIDEO_DURATION_S),
    )


@pytest.mark.parametrize(
    ('tier_prices', 'post_prices', 'expected'),
    [
        ({'RUB': 250, 'USD': 3}, {'RUB': 50, 'USD': 1}, (250, 50)),
        ({'RUB': 0}, {'RUB': 0}, (0, 0)),
        ({'USD': 3}, {'USD': 1}, (None, None)),
        (None, None, (None, None)),
    ],
    ids=['independent-prices', 'free', 'other-currency', 'unknown'],
)
def test_rub_prices_remain_independent_of_account_currency(
    tier_prices: dict[str, float] | None,
    post_prices: dict[str, float] | None,
    expected: tuple[float | None, float | None],
):
    payload = synthetic_post()
    payload['price'] = 9.5
    payload['currencyPrices'] = post_prices
    payload['subscriptionLevel']['price'] = 19.5
    payload['subscriptionLevel']['currencyPrices'] = tier_prices

    post = _map_payload(payload).post

    assert (post.tier_price_rub, post.post_price_rub) == expected


def test_locked_post_with_missing_overview_keeps_access_and_unknown_values():
    payload = synthetic_post()
    for key in (
        'publishTime',
        'tags',
        'count',
        'contentCounters',
        'subscriptionLevel',
        'currencyPrices',
    ):
        payload.pop(key)
    payload.update(hasAccess=False, data=[])

    live = _map_payload(payload)

    assert not live.has_access
    assert live.blocks == []
    assert live.media == {}
    assert (
        live.post.published_at,
        live.post.tier,
        live.post.tier_price_rub,
        live.post.post_price_rub,
    ) == (None, None, None, None)
    assert (
        live.post.tags,
        live.post.content_counters,
        live.post.likes,
        live.post.comments,
    ) == ([], {}, 0, 0)


def test_rich_text_links_and_headers_keep_explicit_breaks_and_blank_blocks():
    live = _map_chunks(
        [
            {
                'type': 'header',
                'content': json.dumps(['Heading', 'header-two', [[0, 0, 7]]]),
                'modificator': '',
            },
            {
                'type': 'link',
                'url': 'https://example.com/lesson',
                'explicit': True,
                'content': json.dumps(
                    ['one\r\ntwo\n', 'unstyled', [[2, 0, 9], [4, 0, 9]]]
                ),
            },
            block_end(),
            text_chunk(''),
            block_end(),
            {**text_chunk('last'), 'modificator': 'BLOCK_END'},
        ]
    )

    link_style = TextStyle(italic=True, underline=True)
    assert live.blocks == [
        TextBlock(
            [TextFragment('Heading', header_level=2, style=TextStyle(bold=True))]
        ),
        TextBlock(
            [
                TextFragment(
                    'one', link_url='https://example.com/lesson', style=link_style
                ),
                LineBreak(),
                TextFragment(
                    'two', link_url='https://example.com/lesson', style=link_style
                ),
                LineBreak(),
            ]
        ),
        ParagraphBreak(),
        TextBlock([]),
        ParagraphBreak(),
        TextBlock([TextFragment('last')]),
        ParagraphBreak(),
    ]


@pytest.mark.parametrize('style', ['ordered', 'checklist'])
def test_nested_lists_keep_text_breaks_and_fall_back_for_unknown_style(style: str):
    live = _map_chunks(
        [
            {
                'type': 'list',
                'style': style,
                'items': [
                    {
                        'data': [
                            text_chunk('parent\nnext'),
                            block_end(),
                            text_chunk(''),
                        ],
                        'items': [{'data': [text_chunk('child\r\nlast')]}],
                    }
                ],
            }
        ]
    )

    expected_style = (
        PostDataChunkTextualList.ListStyle.ordered
        if style == 'ordered'
        else PostDataChunkTextualList.ListStyle.unordered
    )
    assert live.blocks == [
        ListBlock(
            style=expected_style,
            items=[
                ListItem(
                    data=[
                        TextBlock(
                            [TextFragment('parent'), LineBreak(), TextFragment('next')]
                        ),
                        ParagraphBreak(),
                        TextBlock([]),
                    ],
                    nested_items=[
                        ListItem(
                            data=[
                                TextBlock(
                                    [
                                        TextFragment('child'),
                                        LineBreak(),
                                        TextFragment('last'),
                                    ]
                                )
                            ]
                        )
                    ],
                )
            ],
        )
    ]


def test_outputs_own_metadata_downloads_and_styles_without_mutating_the_dto():
    styled = text_chunk('left\nright')
    styled['content'] = json.dumps(['left\nright', 'unstyled', [[0, 0, 10]]])
    payload = synthetic_post()
    payload['data'] = [
        styled,
        {'type': 'list', 'items': [{'data': [styled]}]},
        image_chunk(),
    ]
    dto = PostDTO.model_validate(payload)
    original_dto = dto.model_copy(deep=True)
    first = map_post_dto_to_live(dto, AUTHOR, BoostyOkVideoType.medium)
    second = map_post_dto_to_live(dto, AUTHOR, BoostyOkVideoType.medium)
    original_second = deepcopy(second)
    text = first.blocks[0]
    assert isinstance(text, TextBlock)
    left, _, right = text.fragments
    assert isinstance(left, TextFragment)
    assert isinstance(right, TextFragment)
    assert left.style is not right.style
    left.style.bold = False
    assert right.style.bold
    nested = first.blocks[1]
    assert isinstance(nested, ListBlock)
    nested_text = nested.items[0].data[0]
    assert isinstance(nested_text, TextBlock)
    nested_fragment = nested_text.fragments[0]
    assert isinstance(nested_fragment, TextFragment)
    nested_fragment.style.bold = False
    first.post.tags.append('local edit')
    first.post.content_counters['image'] = 99
    image = first.media[f'image:{IMAGE_ID}'].download
    assert isinstance(image, PostDataChunkImage)
    image.url = 'https://images.example/local-edit'

    assert second == original_second
    assert dto == original_dto


def test_external_identity_keeps_meaningful_query_and_is_owned_by_each_post():
    payload = {**synthetic_post(), 'data': [{'type': 'video', 'url': EXTERNAL_URL}]}
    first = _map_payload(payload)
    second = _map_payload({**payload, 'id': '00000000-0000-4000-8000-000000000002'})
    key = f'external_video:{EXTERNAL_URL}'

    assert first.blocks == second.blocks == [MediaBlock(key)]
    assert list(first.media) == list(second.media) == [key]
    assert first.media[key].kind is MediaKind.external_video
    assert first.media[key].download == PostDataChunkExternalVideo(EXTERNAL_URL)
    assert first.post.id != second.post.id
    assert first.media[key] is not second.media[key]
    download = first.media[key].download
    assert isinstance(download, PostDataChunkExternalVideo)
    download.url = 'https://video.example/replaced'
    assert second.media[key].download == PostDataChunkExternalVideo(EXTERNAL_URL)


@pytest.mark.parametrize(
    ('style_ranges', 'first_style'),
    [
        ([[0, 0, 2]], TextStyle(bold=True)),
        ([[0, 1, 2]], TextStyle()),
    ],
    ids=['cr-attached-to-text', 'standalone-cr'],
)
def test_crlf_split_across_style_runs_remains_one_break(
    style_ranges: list[list[int]],
    first_style: TextStyle,
):
    chunk = text_chunk('A\r\nB')
    chunk['content'] = json.dumps(['A\r\nB', 'unstyled', style_ranges])

    live = _map_chunks([chunk])

    assert live.blocks == [
        TextBlock(
            [TextFragment('A', style=first_style), LineBreak(), TextFragment('B')]
        )
    ]


@pytest.mark.parametrize('inside_list', [False, True], ids=['body', 'nested-list'])
@pytest.mark.parametrize(
    'boundary_in_text', [False, True], ids=['separate', 'attached']
)
def test_paragraph_boundary_is_distinct_from_an_inline_break(
    *,
    inside_list: bool,
    boundary_in_text: bool,
):
    if boundary_in_text:
        inline = [text_chunk('A\n'), text_chunk('B')]
        paragraphs = [
            {**text_chunk('A'), 'modificator': 'BLOCK_END'},
            text_chunk('B'),
        ]
    else:
        inline = [text_chunk('A'), text_chunk('\n'), text_chunk('B'), block_end()]
        paragraphs = [text_chunk('A'), block_end(), text_chunk('B'), block_end()]
    if inside_list:
        inline = [
            {'type': 'list', 'items': [{'data': [], 'items': [{'data': inline}]}]}
        ]
        paragraphs = [
            {'type': 'list', 'items': [{'data': [], 'items': [{'data': paragraphs}]}]}
        ]

    assert _map_chunks(inline).blocks != _map_chunks(paragraphs).blocks


@pytest.mark.parametrize('inside_list', [False, True], ids=['body', 'nested-list'])
def test_consecutive_paragraph_boundaries_keep_empty_and_inline_text_distinct(
    *,
    inside_list: bool,
):
    styled = text_chunk('A\r\n')
    styled['content'] = json.dumps(['A\r\n', 'unstyled', [[0, 0, 3]]])
    styled['modificator'] = 'BLOCK_END'
    chunks = [
        block_end(),
        {**text_chunk(''), 'modificator': 'BLOCK_END'},
        text_chunk(''),
        text_chunk('\n'),
        styled,
    ]
    expected = [
        ParagraphBreak(),
        ParagraphBreak(),
        TextBlock([]),
        TextBlock([LineBreak()]),
        TextBlock([TextFragment('A', style=TextStyle(bold=True)), LineBreak()]),
        ParagraphBreak(),
    ]
    if inside_list:
        chunks = [
            {'type': 'list', 'items': [{'data': [], 'items': [{'data': chunks}]}]}
        ]
        live = _map_chunks(chunks)
        block = live.blocks[0]
        assert isinstance(block, ListBlock)
        assert block.items[0].nested_items[0].data == expected
    else:
        assert _map_chunks(chunks).blocks == expected
