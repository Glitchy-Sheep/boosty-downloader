"""PostStore operations preserve complete snapshots and stable post identity."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import pytest
from support.memory_post_store import MemoryPostStore

from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.domain.stored_post import (
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

if TYPE_CHECKING:
    from boosty_downloader.application.ports import PostStore

FIRST = datetime(2026, 1, 1, tzinfo=timezone.utc)
LATER = FIRST + timedelta(days=7)
FOLDER = 'writer/first-post'
TextFragment = PostDataChunkText.TextFragment


@pytest.fixture
def store() -> PostStore:
    return MemoryPostStore()


@pytest.fixture
def seeded_store() -> PostStore:
    memory = MemoryPostStore()
    memory.seed_post_folder('writer', 'post-1', FOLDER)
    return memory


@pytest.fixture
def record() -> StoredPost:
    nested = ListItem(
        [TextBlock([TextFragment('Nested', style=TextFragment.TextStyle(bold=True))])]
    )
    return StoredPost(
        post=PostMetadata(
            id='post-1',
            author='writer',
            url='https://boosty.to/writer/posts/post-1',
            title='First title',
            created_at=FIRST,
            updated_at=LATER,
            tags=['lesson'],
            content_counters={'file': 2},
        ),
        sync=PostSync(FIRST, LATER, page_template=1),
        blocks=[
            TextBlock([TextFragment('First'), LineBreak(), TextFragment('Second')]),
            ParagraphBreak(),
            ListBlock(
                [ListItem([TextBlock([TextFragment('Parent')])], [nested])],
                PostDataChunkTextualList.ListStyle.ordered,
            ),
            MediaBlock('file:saved'),
        ],
        media={
            'file:saved': MediaEntry(
                MediaKind.file,
                MediaStatus.downloaded,
                FIRST,
                0,
                path='files/saved.zip',
                size=40,
            ),
            'file:removed': MediaEntry(
                MediaKind.file,
                MediaStatus.downloaded,
                FIRST,
                1,
                removed_at=LATER,
                path='files/removed.zip',
                size=20,
            ),
        },
    )


def _mutate_blocks(record: StoredPost) -> None:
    text, _, listing, _ = record.blocks
    assert isinstance(text, TextBlock)
    fragment = text.fragments[0]
    assert isinstance(fragment, TextFragment)
    fragment.text = 'Changed text'
    fragment.style.italic = True
    assert isinstance(listing, ListBlock)
    listing.style = PostDataChunkTextualList.ListStyle.unordered
    nested = listing.items[0].nested_items[0]
    nested_text = nested.data[0]
    assert isinstance(nested_text, TextBlock)
    nested_fragment = nested_text.fragments[0]
    assert isinstance(nested_fragment, TextFragment)
    nested_fragment.style.bold = False
    nested.data.clear()
    listing.items[0].nested_items.clear()
    listing.items.clear()
    record.blocks.clear()


def _mutate_record(record: StoredPost) -> None:
    record.post.title = 'Changed title'
    record.post.tags.append('changed')
    record.post.content_counters['file'] = 0
    record.sync.synced_at = LATER + timedelta(days=1)
    record.sync.page_template = 2
    record.media['file:saved'].status = MediaStatus.deleted
    record.media['file:removed'].path = 'files/changed.zip'
    record.media.clear()
    _mutate_blocks(record)


def test_unknown_post_has_no_location(store: PostStore) -> None:
    assert store.find_post('writer', 'post-1') is None


def test_existing_folder_without_record_is_distinct_from_unknown_post(
    seeded_store: PostStore,
) -> None:
    assert seeded_store.find_post('writer', 'post-1') == LocatedPost(FOLDER)
    assert seeded_store.find_post('writer', 'post-2') is None


def test_round_trip_retains_full_body_and_media_history(
    store: PostStore, record: StoredPost
) -> None:
    expected = deepcopy(record)

    store.save_post(FOLDER, record)

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, expected)
    assert record == expected


def test_same_post_updates_in_place_after_title_change(
    store: PostStore, record: StoredPost
) -> None:
    store.save_post(FOLDER, record)
    record.post.title = 'New title'
    record.sync.page_template = 2
    record.media['file:saved'].status = MediaStatus.deleted

    store.save_post(FOLDER, record)

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, record)


def test_identical_ids_belonging_to_different_authors_are_independent(
    store: PostStore, record: StoredPost
) -> None:
    other = replace(
        record, post=replace(record.post, author='other-writer', title='Other author')
    )

    store.save_post(FOLDER, record)
    store.save_post('other-writer/first-post', other)

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, record)
    assert store.find_post('other-writer', 'post-1') == LocatedPost(
        'other-writer/first-post', other
    )


def test_full_post_ids_distinguish_posts_with_the_same_prefix(
    store: PostStore, record: StoredPost
) -> None:
    other = replace(record, post=replace(record.post, id='post-12'))

    store.save_post(FOLDER, record)
    store.save_post('writer/second-post', other)

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, record)
    assert store.find_post('writer', 'post-12') == LocatedPost(
        'writer/second-post', other
    )


def test_mutating_saved_input_does_not_change_storage(
    store: PostStore, record: StoredPost
) -> None:
    expected = deepcopy(record)
    store.save_post(FOLDER, record)

    _mutate_record(record)

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, expected)


def test_loaded_snapshots_own_all_mutable_values(
    store: PostStore, record: StoredPost
) -> None:
    expected = deepcopy(record)
    store.save_post(FOLDER, record)
    first = store.find_post('writer', 'post-1')
    second = store.find_post('writer', 'post-1')
    assert first is not None
    assert first.record is not None

    _mutate_record(first.record)

    assert second == LocatedPost(FOLDER, expected)
    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, expected)
    assert record == expected


def test_edited_snapshot_changes_storage_only_after_another_save(
    store: PostStore, record: StoredPost
) -> None:
    store.save_post(FOLDER, record)
    loaded = store.find_post('writer', 'post-1')
    assert loaded is not None
    assert loaded.record is not None
    loaded.record.post.tags.append('new tag')
    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, record)

    store.save_post(loaded.folder, loaded.record)

    assert store.find_post('writer', 'post-1') == loaded


def test_folder_choice_does_not_create_or_reserve_a_location(
    store: PostStore, record: StoredPost
) -> None:
    expected = deepcopy(record.post)
    candidate = store.choose_post_folder(record.post)
    assert store.choose_post_folder(record.post) == candidate
    assert record.post == expected
    assert store.find_post('writer', 'post-1') is None
    other = replace(record, post=replace(record.post, id='post-2'))

    store.save_post(candidate, other)

    assert store.find_post('writer', 'post-2') == LocatedPost(candidate, other)
    assert store.find_post('writer', 'post-1') is None


def test_saving_a_record_adopts_its_existing_folder(
    seeded_store: PostStore, record: StoredPost
) -> None:
    seeded_store.save_post(FOLDER, record)

    assert seeded_store.find_post('writer', 'post-1') == LocatedPost(FOLDER, record)


def test_moving_an_existing_post_is_rejected_without_changing_its_record(
    store: PostStore, record: StoredPost
) -> None:
    expected = deepcopy(record)
    store.save_post(FOLDER, record)
    record.post.title = 'Rejected update'

    with pytest.raises(ValueError, match=r'[Ff]older'):
        store.save_post('writer/new-folder', record)

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, expected)


def test_overwriting_another_saved_post_preserves_both_records(
    store: PostStore, record: StoredPost
) -> None:
    other = replace(record, post=replace(record.post, id='post-2', title='Other post'))
    store.save_post(FOLDER, record)
    store.save_post('writer/second-post', other)

    with pytest.raises(ValueError, match=r'[Ff]older'):
        store.save_post(FOLDER, other)

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, record)
    assert store.find_post('writer', 'post-2') == LocatedPost(
        'writer/second-post', other
    )


def test_new_post_cannot_replace_another_posts_record(
    store: PostStore, record: StoredPost
) -> None:
    store.save_post(FOLDER, record)
    other = replace(record, post=replace(record.post, id='post-2'))

    with pytest.raises(ValueError, match=r'[Ff]older'):
        store.save_post(FOLDER, other)

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, record)
    assert store.find_post('writer', 'post-2') is None


def test_seeded_folder_cannot_be_claimed_by_another_post(
    seeded_store: PostStore, record: StoredPost
) -> None:
    other = replace(record, post=replace(record.post, id='post-2'))

    with pytest.raises(ValueError, match=r'[Ff]older'):
        seeded_store.save_post(FOLDER, other)

    assert seeded_store.find_post('writer', 'post-1') == LocatedPost(FOLDER)
    assert seeded_store.find_post('writer', 'post-2') is None


def test_seeded_post_cannot_be_saved_in_a_different_folder(
    seeded_store: PostStore, record: StoredPost
) -> None:
    with pytest.raises(ValueError, match=r'[Ff]older'):
        seeded_store.save_post('writer/new-folder', record)

    assert seeded_store.find_post('writer', 'post-1') == LocatedPost(FOLDER)


def test_losing_and_regaining_access_preserves_saved_record_and_folder(
    store: PostStore, record: StoredPost
) -> None:
    expected = deepcopy(record)
    store.save_post(FOLDER, record)
    locked = LockedPost(
        replace(record.post, title='Locked title'), LATER, 'teasers/first.jpg'
    )

    store.save_locked_post(locked)
    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, expected)
    store.clear_locked_post('writer', 'post-1')

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, expected)


def test_locked_only_post_never_acquires_a_post_folder(
    store: PostStore, record: StoredPost
) -> None:
    store.save_locked_post(LockedPost(record.post, LATER))
    assert store.find_post('writer', 'post-1') is None

    store.clear_locked_post('writer', 'post-1')

    assert store.find_post('writer', 'post-1') is None


def test_clearing_absent_access_observation_preserves_saved_post(
    store: PostStore, record: StoredPost
) -> None:
    store.save_post(FOLDER, record)

    store.clear_locked_post('writer', 'post-1')
    store.clear_locked_post('writer', 'unknown')

    assert store.find_post('writer', 'post-1') == LocatedPost(FOLDER, record)
    assert store.find_post('writer', 'unknown') is None
