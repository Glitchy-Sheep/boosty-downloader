from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LineBreak,
    ListBlock,
    ListItem,
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)

_CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)
_ADDED = _CREATED + timedelta(days=1)
_SYNCED = _ADDED + timedelta(days=1)


@pytest.fixture
def metadata() -> PostMetadata:
    return PostMetadata(
        id='10000000-0000-4000-8000-000000000001',
        author='example_author',
        url='https://boosty.to/example_author/posts/10000000-0000-4000-8000-000000000001',
        title='Example post',
        created_at=_CREATED,
        updated_at=_SYNCED,
    )


@pytest.fixture
def stored_post(metadata: PostMetadata) -> StoredPost:
    return StoredPost(
        post=metadata,
        sync=PostSync(first_downloaded_at=_ADDED, synced_at=_SYNCED),
        blocks=[
            TextBlock(
                [
                    PostDataChunkText.TextFragment(
                        text='Heading',
                        header_level=2,
                        style=PostDataChunkText.TextFragment.TextStyle(bold=True),
                    ),
                    LineBreak(),
                    PostDataChunkText.TextFragment(
                        text='More',
                        link_url='https://example.org',
                        style=PostDataChunkText.TextFragment.TextStyle(
                            italic=True,
                            underline=True,
                        ),
                    ),
                ]
            ),
            ParagraphBreak(),
            TextBlock([LineBreak()]),
            TextBlock([]),
            ListBlock(
                items=[
                    ListItem(
                        data=[
                            TextBlock([PostDataChunkText.TextFragment('First')]),
                            ParagraphBreak(),
                        ],
                        nested_items=[
                            ListItem(
                                data=[
                                    TextBlock(
                                        [
                                            PostDataChunkText.TextFragment('Nested'),
                                            LineBreak(),
                                            PostDataChunkText.TextFragment('Next line'),
                                        ]
                                    )
                                ]
                            )
                        ],
                    )
                ],
                style=PostDataChunkTextualList.ListStyle.ordered,
            ),
            MediaBlock('audio:track-1'),
        ],
        media={
            'audio:track-1': MediaEntry(
                kind=MediaKind.audio,
                status=MediaStatus.downloaded,
                added_at=_ADDED,
                position=0,
                path='audio/track.mp3',
                size=1200,
                title='Track',
                artist='Artist',
                duration=timedelta(seconds=42),
            ),
        },
    )


def test_complete_record_compares_text_formatting_breaks_and_media(
    stored_post: StoredPost,
):
    assert stored_post == deepcopy(stored_post)
    changed = deepcopy(stored_post)
    heading = changed.blocks[0]
    assert isinstance(heading, TextBlock)
    fragment = heading.fragments[0]
    assert isinstance(fragment, PostDataChunkText.TextFragment)
    fragment.style.bold = False
    assert changed != stored_post

    changed = deepcopy(stored_post)
    changed.blocks.pop(2)
    assert changed != stored_post
    changed = deepcopy(stored_post)
    changed.media['audio:track-1'].status = MediaStatus.deleted
    assert changed != stored_post


def test_retained_order_distinguishes_removal_histories(metadata: PostMetadata):
    record = StoredPost(
        post=metadata,
        sync=PostSync(first_downloaded_at=_ADDED, synced_at=_SYNCED),
        blocks=[MediaBlock('image:b')],
        media={
            'image:a': MediaEntry(
                MediaKind.image,
                MediaStatus.downloaded,
                _ADDED,
                0,
                removed_at=_SYNCED,
                path='images/a.jpg',
                size=120,
                width=100,
                height=200,
            ),
            'image:b': MediaEntry(MediaKind.image, MediaStatus.pending, _ADDED, 1),
            'image:c': MediaEntry(
                MediaKind.image,
                MediaStatus.downloaded,
                _ADDED,
                2,
                removed_at=_SYNCED,
                path='images/c.jpg',
                size=240,
            ),
        },
    )
    other_history = deepcopy(record)
    other_history.media['image:a'].position = 2
    other_history.media['image:b'].position = 0
    other_history.media['image:c'].position = 1

    assert record.blocks == other_history.blocks
    assert record != other_history
    assert replace(record, media=dict(reversed(list(record.media.items())))) == record


@pytest.mark.parametrize('status', list(MediaStatus))
def test_file_state_is_independent_of_author_removal(status: MediaStatus):
    entry = MediaEntry(
        kind=MediaKind.file,
        status=status,
        added_at=_ADDED,
        position=0,
        path='files/example.zip',
        filename='example.zip',
        size=0,
        removed_at=_SYNCED,
    )
    current = replace(entry, removed_at=None)

    assert entry != current
    assert entry.status == current.status == status
    assert entry.path == current.path == 'files/example.zip'
    assert entry.added_at == current.added_at == _ADDED
    assert entry.size == current.size == 0


def test_pending_video_can_keep_its_preview_and_reserved_path():
    entry = MediaEntry(
        kind=MediaKind.boosty_video,
        status=MediaStatus.pending,
        added_at=_ADDED,
        position=0,
        path='videos/example.mp4',
        preview_path='previews/example.jpg',
    )

    assert entry.size is None
    assert entry != replace(entry, size=0)
    assert entry.preview_path == 'previews/example.jpg'


def test_same_external_video_in_two_posts_has_independent_state(metadata: PostMetadata):
    media_id = 'external_video:https://example.org/watch?v=example'
    first = StoredPost(
        post=metadata,
        sync=PostSync(first_downloaded_at=_ADDED, synced_at=_SYNCED),
        blocks=[MediaBlock(media_id)],
        media={
            media_id: MediaEntry(
                MediaKind.external_video,
                MediaStatus.failed,
                _ADDED,
                0,
                error='Connection failed',
            )
        },
    )
    second = deepcopy(first)
    second.post.id = '10000000-0000-4000-8000-000000000002'
    second.post.url = f'https://boosty.to/example_author/posts/{second.post.id}'
    second.media[media_id].status = MediaStatus.downloaded
    second.media[media_id].path = 'videos/example.mp4'
    second.media[media_id].size = 1000
    second.media[media_id].error = None

    assert first.media[media_id].status == MediaStatus.failed
    assert first.media[media_id].path is None
    assert first != second


def test_record_and_nested_item_defaults_are_independent(metadata: PostMetadata):
    first = StoredPost(metadata, PostSync(_ADDED, _SYNCED))
    second = StoredPost(replace(metadata), PostSync(_ADDED, _SYNCED))
    first.blocks.append(TextBlock([LineBreak()]))
    first.media['file:example'] = MediaEntry(
        MediaKind.file,
        MediaStatus.pending,
        _ADDED,
        0,
    )
    first_item = ListItem(data=[])
    second_item = ListItem(data=[])
    first_item.nested_items.append(ListItem(data=[]))

    assert second.blocks == []
    assert second.media == {}
    assert second_item.nested_items == []
    assert first.sync.page_template is None
    assert first.sync != replace(first.sync, page_template=1)


def test_metadata_defaults_do_not_share_tags_or_counters():
    first = PostMetadata(
        'first', 'example_author', 'https://example.org/first', '', _CREATED, _CREATED
    )
    second = PostMetadata(
        'second', 'example_author', 'https://example.org/second', '', _CREATED, _CREATED
    )
    first.tags.append('example')
    first.content_counters['file'] = 2

    assert second.tags == []
    assert second.content_counters == {}


def test_locked_overview_keeps_monthly_and_one_off_prices(metadata: PostMetadata):
    priced = replace(
        metadata,
        tier='Tester',
        tier_price_rub=10,
        post_price_rub=50,
        tags=['example'],
        content_counters={'ok_video': 5, 'file': 2},
        published_at=_CREATED,
        likes=3,
        comments=1,
    )
    locked = LockedPost(priced, _SYNCED, teaser_path='teasers/example.jpg')
    saved = StoredPost(deepcopy(priced), PostSync(_ADDED, _SYNCED))

    assert locked.post == saved.post
    assert locked.post.tier_price_rub == 10
    assert locked.post.post_price_rub == 50
    assert metadata != replace(metadata, post_price_rub=0)
    assert metadata != replace(metadata, tier_price_rub=0)
    assert locked == deepcopy(locked)


def test_author_info_distinguishes_unknown_from_empty_and_zero():
    unknown = AuthorInfo(author='example_author', synced_at=_SYNCED)
    empty = replace(unknown, title='', description='', remote_post_count=0)
    complete = replace(
        unknown,
        title='Example blog',
        owner_name='Example owner',
        description='First paragraph.\n\nSecond paragraph.',
        avatar_path='author/avatar.jpg',
        cover_path='author/cover.jpg',
        remote_post_count=12,
    )

    assert unknown != empty
    assert unknown.description is None
    assert unknown.remote_post_count is None
    assert complete.title != complete.owner_name
    assert complete == deepcopy(complete)


def test_records_distinguish_paragraph_boundaries_from_inline_breaks(
    metadata: PostMetadata,
):
    first = TextBlock([PostDataChunkText.TextFragment('First')])
    second = TextBlock([PostDataChunkText.TextFragment('Second')])
    paragraph = StoredPost(
        metadata,
        PostSync(_ADDED, _SYNCED),
        blocks=[first, ParagraphBreak(), second, ParagraphBreak()],
    )
    inline = replace(
        paragraph,
        blocks=[first, TextBlock([LineBreak()]), second, ParagraphBreak()],
    )
    empty_text = replace(
        paragraph,
        blocks=[first, TextBlock([]), second, ParagraphBreak()],
    )

    assert paragraph != inline
    assert paragraph != empty_text
    assert inline != empty_text
    assert ListItem(data=[first, ParagraphBreak(), second]) != ListItem(
        data=[first, TextBlock([LineBreak()]), second]
    )
