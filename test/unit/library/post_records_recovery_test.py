"""Retained native files rebuild a lost post record in the same folder."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from boosty_downloader.application.mappers.live_post import LiveMedia, LivePost
from boosty_downloader.application.media_paths import DiskSnapshot
from boosty_downloader.application.reconcile import reconcile
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.library import LocatedPost
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkFile,
    PostDataChunkImage,
)
from boosty_downloader.domain.stored_post import (
    MediaBlock,
    MediaKind,
    MediaStatus,
    PostMetadata,
)
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

NOW = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
FOLDER = 'writer/2026-10-12 - Original title (abcdefgh)'
MEDIA_BYTES = b'retained native media'


def _live_post(media: LiveMedia) -> LivePost:
    media_id = f'{media.kind.value}:fixture'
    return LivePost(
        post=PostMetadata(
            id='abcdefgh-post',
            author='writer',
            url='https://boosty.to/writer/posts/abcdefgh-post',
            title='Renamed title',
            created_at=NOW,
            updated_at=NOW,
        ),
        has_access=True,
        blocks=[MediaBlock(media_id)],
        media={media_id: media},
    )


def _seed_retained_files(root: Path, media_path: str) -> dict[Path, bytes]:
    folder = root / FOLDER
    retained = {
        folder / media_path: MEDIA_BYTES,
        folder / 'post.html': b'<p>Saved page</p>',
        folder / 'notes.txt': b'User notes',
        folder / 'viewer.json': b'{"viewed": ["abcdefgh-post"]}',
    }
    for path, content in retained.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return retained


@pytest.mark.parametrize(
    ('media', 'media_path'),
    [
        pytest.param(
            LiveMedia(
                kind=MediaKind.image,
                download=PostDataChunkImage(
                    id='fixture', url='https://cdn.example/image'
                ),
                expected_size=len(MEDIA_BYTES),
            ),
            'images/image.jpg',
            id='image',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.file,
                download=PostDataChunkFile(
                    id='fixture',
                    url='https://cdn.example/file',
                    filename='lesson.zip',
                ),
                expected_size=len(MEDIA_BYTES),
                filename='lesson.zip',
            ),
            'files/lesson.zip',
            id='file',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.audio,
                download=PostDataChunkAudio(
                    id='fixture',
                    url='https://cdn.example/audio',
                    title='lesson.mp3',
                ),
                expected_size=len(MEDIA_BYTES),
                title='lesson.mp3',
            ),
            'audio/lesson.mp3',
            id='audio',
        ),
        pytest.param(
            LiveMedia(
                kind=MediaKind.boosty_video,
                download=PostDataChunkBoostyVideo(
                    id='fixture',
                    title='Lesson',
                    url='https://cdn.example/video',
                    quality='high',
                ),
                title='Lesson',
            ),
            'boosty_videos/Lesson (fixture).mp4',
            id='boosty-video',
        ),
    ],
)
def test_lost_record_recovers_native_media_without_another_download_or_folder(
    tmp_path: Path, media: LiveMedia, media_path: str
) -> None:
    live = _live_post(media)
    retained = _seed_retained_files(tmp_path, media_path)
    modified = {path: path.stat().st_mtime_ns for path in retained}
    entries = set(tmp_path.rglob('*'))
    store = JsonPostRecords(tmp_path)
    located = store.find_post(live.post.author, live.post.id)
    assert located == LocatedPost(FOLDER)
    assert located is not None
    observed_size = (tmp_path / located.folder / media_path).stat().st_size
    disk = DiskSnapshot({media_path: observed_size})

    result = reconcile(located.record, live, disk, list(DownloadContentTypeFilter), NOW)

    assert result.download_ids == []
    assert result.record is not None
    entry = result.record.media[f'{media.kind.value}:fixture']
    assert entry.status is MediaStatus.downloaded
    assert entry.path == media_path
    assert entry.size == observed_size
    store.save_post(located.folder, result.record)
    fresh_store = JsonPostRecords(tmp_path)
    assert fresh_store.find_post(live.post.author, live.post.id) == LocatedPost(
        FOLDER, result.record
    )
    assert set(tmp_path.rglob('*')) == entries | {tmp_path / FOLDER / 'post.json'}
    assert {path: path.read_bytes() for path in retained} == retained
    assert {path: path.stat().st_mtime_ns for path in retained} == modified
