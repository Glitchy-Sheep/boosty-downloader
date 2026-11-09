"""A compact canonical library for HTTP reader acceptance tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 11, 9, 12, tzinfo=timezone.utc)
EARLIER = NOW - timedelta(days=1)
OLD_DATE = NOW.replace(month=10)
POST_ID = 'bbbbbbbb-media'
TEXT_ID = 'aaaaaaaa-text'
OLD_ID = 'cccccccc-old'
LOCKED_ID = 'dddddddd-locked'
AUDIO_ID = 'audio:shared'
AUDIO_PATH = 'audio/песня 100% #.mp3'
IMAGE_PATH = 'images/кадр 100% #.png'
MEDIA_BYTES = b'0123456789abcde'


@dataclass(frozen=True, slots=True)
class ReadLibrary:
    root: Path
    store: JsonPostStore
    reader: JsonLibraryReader
    record: StoredPost
    folder: str


def make_record(post_id: str, title: str, created_at: datetime = NOW) -> StoredPost:
    return StoredPost(
        PostMetadata(
            post_id,
            'writer',
            f'https://boosty.to/writer/posts/{post_id}',
            title,
            created_at,
            created_at,
        ),
        PostSync(NOW, NOW),
        [
            TextBlock(
                [PostDataChunkText.TextFragment('Saved body <script> Shader lesson')]
            )
        ],
    )


def save_record(root: Path, store: JsonPostStore, record: StoredPost) -> str:
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    for entry in record.media.values():
        if entry.status is MediaStatus.downloaded and entry.path is not None:
            path = root / folder / entry.path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(MEDIA_BYTES[: entry.size])
    return folder


def _media_record() -> StoredPost:
    record = make_record(POST_ID, 'Shader lesson')
    record.post.tags = ['lesson', 'Mix', 'lesson']
    record.post.tier = 'Supporter'
    record.post.tier_price_rub = 150.5
    record.post.post_price_rub = 75.0
    record.media = {
        'image:cover': MediaEntry(
            MediaKind.image,
            MediaStatus.downloaded,
            EARLIER,
            0,
            path=IMAGE_PATH,
            size=10,
        ),
        AUDIO_ID: MediaEntry(
            MediaKind.audio,
            MediaStatus.downloaded,
            NOW,
            1,
            path=AUDIO_PATH,
            size=15,
            title='A track',
            artist='An artist',
            duration=timedelta(seconds=90),
        ),
        'boosty_video:pending': MediaEntry(
            MediaKind.boosty_video, MediaStatus.pending, NOW, 2, title='Later video'
        ),
        'file:failed': MediaEntry(
            MediaKind.file,
            MediaStatus.failed,
            NOW,
            3,
            filename='missing.zip',
            error='Unavailable transfer',
        ),
        'file:removed': MediaEntry(
            MediaKind.file,
            MediaStatus.downloaded,
            EARLIER,
            4,
            removed_at=NOW,
            path='files/retained.pdf',
            size=7,
        ),
        'external_video:https://example.test/watch?a=b:c': MediaEntry(
            MediaKind.external_video,
            MediaStatus.downloaded,
            NOW,
            5,
            removed_at=NOW,
            path='external_videos/kept.mp4',
            size=4,
        ),
        'file:never': MediaEntry(
            MediaKind.file, MediaStatus.pending, EARLIER, 6, removed_at=NOW
        ),
    }
    record.blocks.extend(
        MediaBlock(key)
        for key, entry in record.media.items()
        if entry.removed_at is None
    )
    return record


def _save_other_posts(root: Path, store: JsonPostStore) -> None:
    text = make_record(TEXT_ID, 'Всё <script> шейдеры', EARLIER)
    text.post.tags = ['text']
    save_record(root, store, text)
    old = make_record(OLD_ID, 'Old recording', OLD_DATE)
    old.blocks.clear()
    old.media['boosty_video:old'] = MediaEntry(
        MediaKind.boosty_video,
        MediaStatus.downloaded,
        OLD_DATE,
        0,
        path='old.mp4',
        size=4,
    )
    old.blocks.append(MediaBlock('boosty_video:old'))
    save_record(root, store, old)
    JsonPostMarks(root).save_marks('writer', OLD_ID, PostMarks(seen_at=NOW))
    locked = make_record(LOCKED_ID, 'Locked', NOW + timedelta(days=1)).post
    locked.content_counters = {
        'image': 2,
        'ok_video': 2,
        'video': 1,
        'file': 4,
        'audio': 5,
    }
    store.save_locked_post(LockedPost(locked, NOW, teaser_path='locked/teaser.jpg'))
    teaser = root / 'writer/locked/teaser.jpg'
    teaser.parent.mkdir(parents=True)
    teaser.write_bytes(b'teaser')


def make_library(root: Path) -> ReadLibrary:
    initialize_library(root)
    store = JsonPostStore(root)
    store.save_author(
        AuthorInfo(
            'writer',
            NOW,
            title='Local writer',
            description='Two paragraphs\n\nSecond',
            avatar_path='avatar.jpg',
            cover_path='cover.jpg',
        )
    )
    store.save_author(AuthorInfo('empty', NOW))
    record = _media_record()
    folder = save_record(root, store, record)
    JsonPostMarks(root).save_marks(
        'writer',
        POST_ID,
        PostMarks(
            seen_at=EARLIER, favorite=True, positions={AUDIO_ID: PlaybackPosition(34.0)}
        ),
    )
    _save_other_posts(root, store)
    reader = JsonLibraryReader(root)
    reader.prepare()
    return ReadLibrary(root, store, reader, record, folder)
