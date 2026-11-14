"""Thumbnail references retain record versions, ownership and original-media history."""

from dataclasses import replace
from json import dumps, loads
from pathlib import Path

import pytest

from boosty_downloader.application.mappers.live_post import LiveMedia, LivePost
from boosty_downloader.application.reconcile import reconcile
from boosty_downloader.domain.disk_snapshot import DiskSnapshot
from boosty_downloader.domain.stored_post import (
    LockedPost,
    MediaKind,
    MediaStatus,
    StoredPost,
)
from boosty_downloader.infrastructure.library._author_json import (
    decode_locked_posts,
    encode_locked_posts,
)
from boosty_downloader.infrastructure.library._post_json import (
    decode_post_record,
    encode_post_record,
)
from boosty_downloader.infrastructure.library.author_records import (
    clear_locked_post,
    read_locked_posts,
    save_locked_post,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidAuthorRecordError,
    InvalidPostRecordError,
    UnsupportedAuthorSchemaError,
    UnsupportedPostSchemaError,
)
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

FIXTURES = Path(__file__).parent / 'fixtures'
MEDIA_ID = 'image:photo'
LOCKED_ID = 'locked-post-full-id'
THUMBNAIL = '.boosty-downloader/thumbs/post-photo.jpg'
INVALID_PATHS = (
    '',
    'photo.jpg',
    'thumbs/photo.jpg',
    'writer/.boosty-downloader/thumbs/photo.jpg',
    '/.boosty-downloader/thumbs/photo.jpg',
    'C:/.boosty-downloader/thumbs/photo.jpg',
    'https://example.com/photo.jpg',
    '.boosty-downloader/teasers/photo.jpg',
    '.boosty-downloader/thumbs',
    '.boosty-downloader/thumbs/',
    '.boosty-downloader/thumbs/nested/photo.jpg',
    '.boosty-downloader/thumbs/../photo.jpg',
    '.boosty-downloader//thumbs/photo.jpg',
    '.boosty-downloader/./thumbs/photo.jpg',
    '.boosty-downloader/thumbs/..',
    '.boosty-downloader/thumbs/photo\\name.jpg',
    '.boosty-downloader/thumbs/photo\x00.jpg',
    '.boosty-downloader/thumbs/photo\n.jpg',
    '.boosty-downloader/thumbs/photo:stream.jpg',
    '.boosty-downloader/thumbs/photo?.jpg',
    '.boosty-downloader/thumbs/CON.jpg',
    '.boosty-downloader/thumbs/CON .jpg',
    '.boosty-downloader/thumbs/LPT1 .png',
    '.boosty-downloader/thumbs/COM¹.jpg',
    '.boosty-downloader/thumbs/CONIN$.jpg',
    '.boosty-downloader/thumbs/photo.jpg.',
    '.boosty-downloader/thumbs/photo.jpg ',
    '.boosty-downloader/thumbs/' + 'a' * 241,
)


@pytest.fixture
def record() -> StoredPost:
    return decode_post_record((FIXTURES / 'post_v1.json').read_bytes())


@pytest.fixture
def locked() -> LockedPost:
    data = (FIXTURES / 'locked_v1.json').read_bytes()
    return decode_locked_posts(data, author='writer')[LOCKED_ID]


@pytest.mark.parametrize(
    'path', [None, THUMBNAIL, '.boosty-downloader/thumbs/Урок.png']
)
def test_v2_round_trip_preserves_paths_without_requiring_files(
    record: StoredPost, locked: LockedPost, path: str | None, tmp_path: Path
) -> None:
    record.media[MEDIA_ID].thumbnail_path = path
    locked.teaser_thumbnail_path = path
    store = JsonPostStore(tmp_path)
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    store.save_locked_post(locked)
    saved = store.find_post('writer', record.post.id)
    assert saved is not None
    assert saved.record == record
    assert store.load_locked_post('writer', LOCKED_ID) == locked
    assert not (tmp_path / 'writer/.boosty-downloader/thumbs').exists()
    assert loads((tmp_path / folder / 'post.json').read_bytes())['schema_version'] == 2
    assert (
        loads(encode_locked_posts('writer', {LOCKED_ID: locked}))['schema_version'] == 2
    )


@pytest.mark.parametrize('path', [None, THUMBNAIL])
def test_v1_rejects_new_fields_even_when_null(path: str | None) -> None:
    post = loads((FIXTURES / 'post_v1.json').read_bytes())
    post['media'][MEDIA_ID]['thumbnail_path'] = path
    locked = loads((FIXTURES / 'locked_v1.json').read_bytes())
    locked['posts'][LOCKED_ID]['teaser_thumbnail_path'] = path
    with pytest.raises(InvalidPostRecordError, match='thumbnail_path'):
        decode_post_record(dumps(post).encode())
    with pytest.raises(InvalidAuthorRecordError, match='teaser_thumbnail_path'):
        decode_locked_posts(dumps(locked).encode(), author='writer')


@pytest.mark.parametrize('path', INVALID_PATHS)
def test_invalid_thumbnail_paths_fail_on_read_and_write(
    record: StoredPost, locked: LockedPost, path: str
) -> None:
    post = loads(encode_post_record(record))
    post['media'][MEDIA_ID]['thumbnail_path'] = path
    locked_json = loads(encode_locked_posts('writer', {LOCKED_ID: locked}))
    locked_json['posts'][LOCKED_ID]['teaser_thumbnail_path'] = path
    record.media[MEDIA_ID].thumbnail_path = locked.teaser_thumbnail_path = path
    with pytest.raises(InvalidPostRecordError):
        encode_post_record(record)
    with pytest.raises(InvalidPostRecordError):
        decode_post_record(dumps(post).encode())
    with pytest.raises(InvalidAuthorRecordError):
        encode_locked_posts('writer', {LOCKED_ID: locked})
    with pytest.raises(InvalidAuthorRecordError):
        decode_locked_posts(dumps(locked_json).encode(), author='writer')


def _snapshot(root: Path) -> dict[Path, tuple[bytes, int]]:
    return {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob('*')
        if path.is_file()
    }


def test_mixed_version_reads_leave_golden_bytes_and_mtimes_unchanged(
    record: StoredPost, locked: LockedPost, tmp_path: Path
) -> None:
    store = JsonPostStore(tmp_path)
    old_folder = store.choose_post_folder(record.post)
    old_post_path = tmp_path / old_folder / 'post.json'
    old_post_path.parent.mkdir(parents=True)
    old_post_path.write_bytes((FIXTURES / 'post_v1.json').read_bytes())
    old_locked_path = tmp_path / 'writer/.boosty-downloader/locked.json'
    old_locked_path.parent.mkdir()
    old_locked_path.write_bytes((FIXTURES / 'locked_v1.json').read_bytes())
    golden_before = _snapshot(tmp_path)
    new = replace(record, post=replace(record.post, id='new-post-full-id'))
    new.media = {MEDIA_ID: replace(record.media[MEDIA_ID], thumbnail_path=THUMBNAIL)}
    store.save_post(store.choose_post_folder(new.post), new)
    new_locked = replace(
        locked,
        post=replace(locked.post, author='another'),
        teaser_thumbnail_path=THUMBNAIL,
    )
    store.save_locked_post(new_locked)
    before = _snapshot(tmp_path)
    assert {path: before[path] for path in golden_before} == golden_before

    for expected in (record, new):
        saved = store.find_post(expected.post.author, expected.post.id)
        assert saved is not None
        assert saved.record == expected
    assert record.media[MEDIA_ID].thumbnail_path is None
    assert store.load_locked_post('writer', LOCKED_ID) == locked
    assert locked.teaser_thumbnail_path is None
    assert store.load_locked_post('another', LOCKED_ID) == new_locked
    assert _snapshot(tmp_path) == before

    store.save_post(old_folder, record)
    store.save_locked_post(locked)
    assert loads(old_post_path.read_bytes())['schema_version'] == 2
    assert loads(old_locked_path.read_bytes())['schema_version'] == 2
    saved = store.find_post('writer', record.post.id)
    assert saved is not None
    assert saved.record == record
    assert store.load_locked_post('writer', LOCKED_ID) == locked


@pytest.mark.parametrize('removed', [False, True])
def test_reconciliation_retains_thumbnail_when_original_disappears(
    record: StoredPost, *, removed: bool
) -> None:
    record.media[MEDIA_ID].thumbnail_path = THUMBNAIL
    live = LivePost(
        record.post,
        has_access=True,
        blocks=[] if removed else record.blocks,
        media={} if removed else {MEDIA_ID: LiveMedia(MediaKind.image, download=None)},
    )
    result = reconcile(record, live, DiskSnapshot({}), [], record.sync.synced_at)
    assert result.record is not None
    image = decode_post_record(encode_post_record(result.record)).media[MEDIA_ID]
    assert image.thumbnail_path == THUMBNAIL
    assert image.status is MediaStatus.deleted
    assert image.path == record.media[MEDIA_ID].path
    assert (image.removed_at is not None) is removed


@pytest.mark.parametrize('version', [1, 2])
def test_locked_unknown_fields_remain_invalid(version: int) -> None:
    document = loads((FIXTURES / 'locked_v1.json').read_bytes())
    document['schema_version'] = version
    document['posts'][LOCKED_ID]['future_field'] = 'retained data'
    with pytest.raises(InvalidAuthorRecordError):
        decode_locked_posts(dumps(document).encode(), author='writer')


def test_future_post_save_preserves_record_and_neighbors(
    record: StoredPost, tmp_path: Path
) -> None:
    store = JsonPostStore(tmp_path)
    folder = store.choose_post_folder(record.post)
    path = tmp_path / folder / 'post.json'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"schema_version": 3, "future_field": "retained"}')
    (path.parent / 'original.jpg').write_bytes(b'original')
    before = _snapshot(tmp_path)
    with pytest.raises(UnsupportedPostSchemaError):
        store.save_post(folder, record)
    assert _snapshot(tmp_path) == before


@pytest.mark.parametrize('operation', ['read', 'save', 'clear'])
def test_future_locked_operations_preserve_record_and_neighbors(
    locked: LockedPost, tmp_path: Path, operation: str
) -> None:
    path = tmp_path / 'writer/.boosty-downloader/locked.json'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"schema_version": 3, "future_field": "retained"}')
    (path.parent / 'teaser.jpg').write_bytes(b'teaser')
    before = _snapshot(tmp_path)
    operations = {
        'read': lambda: read_locked_posts(tmp_path, 'writer'),
        'save': lambda: save_locked_post(tmp_path, locked),
        'clear': lambda: clear_locked_post(tmp_path, 'writer', LOCKED_ID),
    }
    with pytest.raises(UnsupportedAuthorSchemaError):
        operations[operation]()
    assert _snapshot(tmp_path) == before
