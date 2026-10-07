"""Content reconciliation keeps saved history separate from live API metadata."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from boosty_downloader.application.mappers.live_post import LiveMedia, LivePost
from boosty_downloader.application.reconcile import prepare_record
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkFile,
    PostDataChunkText,
)
from boosty_downloader.domain.stored_post import (
    ListBlock,
    ListItem,
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

FIRST = datetime(2026, 1, 1, tzinfo=timezone.utc)
NOW = FIRST + timedelta(days=1)
LATER = NOW + timedelta(days=1)
A, B, C, X = 'file:A', 'file:B', 'file:C', 'file:X'


def _live(*media_ids: str) -> LivePost:
    return LivePost(
        post=PostMetadata(
            id='post-fixture',
            author='fixture',
            url='https://boosty.to/fixture/posts/post-fixture',
            title='Lesson',
            created_at=FIRST,
            updated_at=FIRST,
            tags=['lesson'],
            content_counters={'file': len(set(media_ids))},
        ),
        has_access=True,
        blocks=[MediaBlock(media_id) for media_id in media_ids],
        media={
            media_id: LiveMedia(
                kind=MediaKind.file,
                download=None,
                filename=f'{media_id}.zip',
                expected_size=999,
            )
            for media_id in media_ids
        },
    )


def _stored(*media_ids: str) -> StoredPost:
    live = _live(*media_ids)
    return StoredPost(
        post=live.post,
        blocks=live.blocks,
        sync=PostSync(FIRST, FIRST, page_template=4),
        media={
            media_id: MediaEntry(
                kind=MediaKind.file,
                status=MediaStatus.downloaded,
                added_at=FIRST,
                position=position,
                path=f'files/{media_id}.zip',
                size=12,
                filename=f'{media_id}.zip',
                preview_path='images/preview.jpg',
                error='last result',
            )
            for position, media_id in enumerate(media_ids)
        },
    )


def _nested_list() -> ListBlock:
    fragment = PostDataChunkText.TextFragment('Nested')
    fragment.style.bold = True
    child = ListItem(data=[TextBlock([fragment]), ParagraphBreak()])
    return ListBlock(items=[ListItem(data=[], nested_items=[child])])


def _nested_text(block: ListBlock) -> PostDataChunkText.TextFragment:
    text = block.items[0].nested_items[0].data[0]
    assert isinstance(text, TextBlock)
    fragment = text.fragments[0]
    assert isinstance(fragment, PostDataChunkText.TextFragment)
    return fragment


def test_new_locked_post_has_no_saved_record():
    live = _live(A)
    live.has_access = False

    assert prepare_record(None, live, NOW) is None


def test_lost_access_returns_an_equal_independent_saved_record():
    stored = _stored(A)
    stored.blocks.append(_nested_list())
    original = deepcopy(stored)
    live = _live(B)
    live.has_access = False
    live.post.title = 'Locked replacement'

    result = prepare_record(stored, live, NOW)

    assert result == original
    assert result is not stored
    assert result is not None
    block = result.blocks[-1]
    assert isinstance(block, ListBlock)
    _nested_text(block).style.bold = False
    result.post.tags.append('local edit')
    result.media[A].path = 'files/edited.zip'
    result.sync.page_template = 99
    assert stored == original


def test_new_record_keeps_duplicate_body_references_but_one_inventory_entry():
    live = _live(B, A)
    live.blocks = [MediaBlock(A), ParagraphBreak(), MediaBlock(B), MediaBlock(A)]

    result = prepare_record(None, live, NOW)

    assert result is not None
    assert result.post == live.post
    assert result.post is not live.post
    assert result.blocks == live.blocks
    assert result.blocks is not live.blocks
    assert result.sync == PostSync(first_downloaded_at=NOW, synced_at=NOW)
    assert list(result.media) == [A, B]
    for position, media_id in enumerate([A, B]):
        assert result.media[media_id] == MediaEntry(
            kind=MediaKind.file,
            status=MediaStatus.pending,
            added_at=NOW,
            position=position,
            filename=f'{media_id}.zip',
        )


def test_unchanged_content_only_refreshes_the_synchronization_time():
    stored = _stored(A)
    expected = deepcopy(stored)
    expected.sync.synced_at = NOW

    assert prepare_record(stored, _live(A), NOW) == expected


@pytest.mark.parametrize(
    'incoming',
    [
        LiveMedia(
            kind=MediaKind.file,
            download=None,
            expected_size=4000,
            preview_url='https://images.example/new',
        ),
        LiveMedia(
            kind=MediaKind.file,
            download=None,
            expected_size=4000,
            title='New title',
            filename='new.zip',
            artist='New artist',
            duration=timedelta(seconds=40),
            width=1280,
            height=720,
            preview_url='https://images.example/new',
        ),
    ],
    ids=['missing-descriptions', 'updated-descriptions'],
)
def test_edits_refresh_descriptions_without_losing_local_state(incoming: LiveMedia):
    stored = _stored(A)
    stored.media[A] = replace(
        stored.media[A],
        title='Old title',
        artist='Old artist',
        duration=timedelta(seconds=20),
        width=640,
        height=480,
    )
    live = _live(A)
    live.post = replace(live.post, title='Edited', tags=[], likes=3, updated_at=NOW)
    live.media[A] = incoming

    result = prepare_record(stored, live, NOW)

    assert result is not None
    assert result.post == live.post
    assert result.sync == replace(stored.sync, synced_at=NOW)
    assert result.media[A] == replace(
        stored.media[A],
        title=incoming.title,
        filename=incoming.filename,
        artist=incoming.artist,
        duration=incoming.duration,
        width=incoming.width,
        height=incoming.height,
    )


@pytest.mark.parametrize('status', list(MediaStatus))
def test_removal_and_return_preserve_each_local_state_and_first_removal_time(
    status: MediaStatus,
):
    stored = _stored(A)
    stored.media[A].status = status
    original = deepcopy(stored.media[A])

    removed = prepare_record(stored, _live(), NOW)
    assert removed is not None
    assert removed.media[A] == replace(original, removed_at=NOW)
    absent_again = prepare_record(removed, _live(), LATER)
    assert absent_again is not None
    assert absent_again.media[A] == removed.media[A]
    returned = prepare_record(absent_again, _live(A), LATER)
    assert returned is not None
    assert returned.media[A] == original
    removed_again = prepare_record(returned, _live(), LATER + timedelta(days=1))
    assert removed_again is not None
    assert removed_again.media[A].removed_at == LATER + timedelta(days=1)


def test_old_positions_and_current_body_order_determine_inventory_order():
    stored = _stored(B, A, C)
    stored.media = {C: stored.media[C], A: stored.media[A], B: stored.media[B]}

    result = prepare_record(stored, _live(X, C, B), NOW)

    assert result is not None
    assert list(result.media) == [X, C, A, B]
    assert [entry.position for entry in result.media.values()] == [0, 1, 2, 3]
    assert result.media[A].removed_at == NOW
    assert result.media[X].added_at == NOW
    assert result.blocks == [MediaBlock(X), MediaBlock(C), MediaBlock(B)]


@pytest.mark.parametrize('history', [[A, B, C], [B, C, A]])
def test_successive_removals_do_not_merge_distinct_inventory_histories(
    history: list[str],
):
    first = prepare_record(_stored(*history), _live(B, C), NOW)
    assert first is not None
    second = prepare_record(first, _live(B), LATER)
    assert second is not None

    assert list(first.media) == history
    assert list(second.media) == history
    assert second.media[A].removed_at == NOW
    assert second.media[C].removed_at == LATER


def test_an_unfinished_upload_keeps_its_identity_and_added_time_when_ready():
    live = _live(A)
    pending = prepare_record(None, live, NOW)
    assert pending is not None
    live.media[A].download = PostDataChunkFile(
        id='A',
        url='https://cdn.example/ready?signature=new',
        filename=f'{A}.zip',
        size=999,
    )

    ready = prepare_record(pending, live, LATER)

    assert ready is not None
    assert ready.media == pending.media
    assert ready.blocks == pending.blocks
    assert ready.sync == replace(pending.sync, synced_at=LATER)


@pytest.mark.parametrize('existing', [False, True])
def test_preparation_and_output_edits_leave_live_and_saved_inputs_owned(
    *, existing: bool
):
    stored = None
    if existing:
        stored = _stored(A, B)
    live = _live(A)
    live.blocks.append(_nested_list())
    original_live, original_stored = deepcopy(live), deepcopy(stored)

    result = prepare_record(stored, live, NOW)

    assert result is not None
    block = result.blocks[-1]
    assert isinstance(block, ListBlock)
    _nested_text(block).style.bold = False
    result.post.tags.append('local edit')
    result.post.content_counters['file'] = 99
    result.media[A].path = 'files/local-edit.zip'
    result.sync.page_template = 99
    if existing:
        result.media[B].path = 'files/removed-edit.zip'
    assert live == original_live
    assert stored == original_stored
