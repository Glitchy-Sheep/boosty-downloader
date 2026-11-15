"""Covers follow the current body and observed files, not retained inventory order."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from boosty_downloader.domain.disk_snapshot import DiskSnapshot
from boosty_downloader.domain.post_cover import select_locked_cover, select_post_cover
from boosty_downloader.domain.stored_post import (
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)

NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
FIRST_IMAGE = 'image:first'
SECOND_IMAGE = 'image:second'
FIRST_VIDEO = 'boosty_video:first'
SECOND_VIDEO = 'boosty_video:second'


@pytest.fixture
def record() -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            'post', 'writer', 'https://boosty.to/writer/posts/post', 'Post', NOW, NOW
        ),
        sync=PostSync(NOW, NOW),
        blocks=[
            MediaBlock(FIRST_VIDEO),
            MediaBlock(SECOND_IMAGE),
            MediaBlock(FIRST_IMAGE),
            MediaBlock(SECOND_VIDEO),
        ],
        media={
            FIRST_IMAGE: MediaEntry(
                MediaKind.image, MediaStatus.downloaded, NOW, 0, path='images/first.jpg'
            ),
            SECOND_IMAGE: MediaEntry(
                MediaKind.image,
                MediaStatus.downloaded,
                NOW,
                1,
                path='images/second.jpg',
            ),
            FIRST_VIDEO: MediaEntry(
                MediaKind.boosty_video,
                MediaStatus.pending,
                NOW,
                2,
                preview_path='previews/first.jpg',
            ),
            SECOND_VIDEO: MediaEntry(
                MediaKind.boosty_video,
                MediaStatus.downloaded,
                NOW,
                3,
                preview_path='previews/second.jpg',
            ),
        },
    )


@pytest.fixture
def disk() -> DiskSnapshot:
    return DiskSnapshot(
        {
            'images/first.jpg': 10,
            'images/second.jpg': 20,
            'previews/first.jpg': 30,
            'previews/second.jpg': 40,
        }
    )


def test_downloaded_image_wins_over_earlier_video_in_current_body_order(
    record: StoredPost,
    disk: DiskSnapshot,
) -> None:
    before = deepcopy(record)
    assert select_post_cover(record, disk) == 'images/second.jpg'
    assert record == before


@pytest.mark.parametrize(
    'status',
    [
        MediaStatus.pending,
        MediaStatus.failed,
        MediaStatus.deleted,
        MediaStatus.unavailable,
    ],
)
def test_current_image_without_downloaded_state_does_not_become_cover(
    record: StoredPost,
    disk: DiskSnapshot,
    status: MediaStatus,
) -> None:
    record.media[SECOND_IMAGE].status = status
    assert select_post_cover(record, disk) == 'images/first.jpg'


def test_removed_image_and_inventory_only_image_do_not_become_cover(
    record: StoredPost,
    disk: DiskSnapshot,
) -> None:
    record.media[SECOND_IMAGE].removed_at = NOW
    record.blocks = [MediaBlock(SECOND_IMAGE), MediaBlock(FIRST_VIDEO)]
    assert select_post_cover(record, disk) == 'previews/first.jpg'


@pytest.mark.parametrize('size', [None, 0])
def test_image_with_no_usable_file_yields_to_the_next_image(
    record: StoredPost,
    disk: DiskSnapshot,
    size: int | None,
) -> None:
    files = dict(disk.files)
    files.pop('images/second.jpg')
    if size is not None:
        files['images/second.jpg'] = size
    assert select_post_cover(record, DiskSnapshot(files)) == 'images/first.jpg'


@pytest.mark.parametrize('status', list(MediaStatus))
def test_first_video_preview_does_not_require_the_video_file(
    record: StoredPost,
    disk: DiskSnapshot,
    status: MediaStatus,
) -> None:
    record.blocks = [MediaBlock(FIRST_VIDEO), MediaBlock(SECOND_VIDEO)]
    record.media[FIRST_VIDEO].status = status
    assert select_post_cover(record, disk) == 'previews/first.jpg'


@pytest.mark.parametrize(
    'preview_path', [None, 'previews/missing.jpg', 'previews/empty.jpg']
)
def test_missing_first_video_preview_does_not_fall_through_to_later_videos(
    record: StoredPost,
    disk: DiskSnapshot,
    preview_path: str | None,
) -> None:
    record.blocks = [MediaBlock(FIRST_VIDEO), MediaBlock(SECOND_VIDEO)]
    record.media[FIRST_VIDEO].preview_path = preview_path
    observed = DiskSnapshot({**disk.files, 'previews/empty.jpg': 0})
    assert select_post_cover(record, observed) is None


def test_first_current_video_ignores_removed_predecessor(
    record: StoredPost,
    disk: DiskSnapshot,
) -> None:
    record.blocks = [MediaBlock(FIRST_VIDEO), MediaBlock(SECOND_VIDEO)]
    record.media[FIRST_VIDEO].removed_at = NOW
    assert select_post_cover(record, disk) == 'previews/second.jpg'


def test_external_video_has_no_boosty_preview_fallback(
    record: StoredPost,
    disk: DiskSnapshot,
) -> None:
    record.blocks = [MediaBlock(FIRST_VIDEO)]
    record.media[FIRST_VIDEO].kind = MediaKind.external_video
    assert select_post_cover(record, disk) is None


def test_empty_body_has_no_cover_from_retained_media(
    record: StoredPost,
    disk: DiskSnapshot,
) -> None:
    record.blocks = []
    assert select_post_cover(record, disk) is None


def test_confirmed_alias_returns_the_observed_portable_path(record: StoredPost) -> None:
    disk = DiskSnapshot(
        files={'IMAGES/SECOND.JPG': 5},
        aliases={'images/second.jpg': 'IMAGES/SECOND.JPG'},
    )
    assert select_post_cover(record, disk) == 'IMAGES/SECOND.JPG'


@pytest.mark.parametrize('size', [None, 0, 5])
def test_locked_cover_uses_a_nonempty_author_relative_teaser(
    record: StoredPost,
    size: int | None,
) -> None:
    path = '.boosty-downloader/teasers/post.jpg'
    locked = LockedPost(record.post, NOW, teaser_path=path)
    disk = DiskSnapshot({path: size} if size is not None else {})
    assert select_locked_cover(locked, disk) == (path if size else None)
