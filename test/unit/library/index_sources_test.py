"""The index reads canonical snapshots without observing unrelated media or caches."""

from __future__ import annotations

import errno
import os
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from boosty_downloader.domain.library import PostAccess
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
from boosty_downloader.infrastructure.library._author_json import (
    encode_author_record,
    encode_locked_posts,
)
from boosty_downloader.infrastructure.library._post_json import encode_post_record
from boosty_downloader.infrastructure.library._viewer_json import encode_viewer_record
from boosty_downloader.infrastructure.library.errors import (
    AmbiguousPostFolderError,
    InvalidAuthorRecordError,
    InvalidPostRecordError,
    InvalidViewerRecordError,
)
from boosty_downloader.infrastructure.library.index_sources import (
    AuthorSource,
    SourceFingerprint,
    scan_authors,
    scan_posts,
)
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

if TYPE_CHECKING:
    from collections.abc import Iterator

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
LATER = NOW + timedelta(days=7)
POST_ID = 'abcdefgh-first'
IMAGE_ID = 'image:cover'
VIDEO_ID = 'boosty_video:lesson'


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / 'library'


@pytest.fixture
def record() -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            id=POST_ID,
            author='writer',
            url=f'https://boosty.to/writer/posts/{POST_ID}',
            title='Saved lesson',
            created_at=NOW,
            updated_at=NOW,
            tags=['lesson'],
        ),
        sync=PostSync(NOW, NOW, page_template=1),
        blocks=[
            TextBlock([PostDataChunkText.TextFragment('Saved body')]),
            MediaBlock(IMAGE_ID),
            MediaBlock(VIDEO_ID),
        ],
        media={
            IMAGE_ID: MediaEntry(
                MediaKind.image,
                MediaStatus.downloaded,
                NOW,
                0,
                path='images/cover.jpg',
                size=12,
            ),
            VIDEO_ID: MediaEntry(
                MediaKind.boosty_video,
                MediaStatus.pending,
                LATER,
                1,
                preview_path='video/preview.jpg',
            ),
        },
    )


def _save(root: Path, record: StoredPost) -> Path:
    store = JsonPostStore(root)
    folder = store.choose_post_folder(record.post)
    store.save_post(folder, record)
    return root / folder


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _fingerprint(path: Path) -> SourceFingerprint:
    info = path.stat()
    return SourceFingerprint(info.st_mtime_ns, info.st_size)


def _symlink(target: Path, link: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except NotImplementedError:
        pytest.skip('Symbolic links are unavailable')
    except OSError as error:
        if error.errno in {errno.EPERM, errno.EACCES, errno.ENOTSUP}:
            pytest.skip('Symbolic links are unavailable')
        raise


def test_absent_root_is_not_created(root: Path) -> None:
    assert list(scan_authors(root)) == []
    assert list(scan_posts(root, AuthorSource('writer'))) == []
    assert not root.exists()


def test_only_canonical_records_prove_author_folders(root: Path) -> None:
    _write(root / 'unrelated/notes.txt', b'not an author')
    _write(root / '.boosty-downloader/library.sqlite', b'not a database')
    _write(root / 'cache.db', b'legacy cache is not an index source')
    recordless = root / 'recordless/2026-10-25 - Title (abcdefgh)'
    _write(recordless / 'viewer.json', b'malformed but no post record')
    assert list(scan_authors(root)) == []
    assert list(scan_posts(root, AuthorSource('recordless'))) == []


def test_author_only_and_locked_only_are_index_sources(
    root: Path, record: StoredPost
) -> None:
    store = JsonPostStore(root)
    info = AuthorInfo('alone', NOW, title='Author without posts')
    store.save_author(info)
    locked = LockedPost(record.post, LATER)
    store.save_locked_post(locked)
    authors = list(scan_authors(root))
    assert [source.author for source in authors] == ['alone', 'writer']
    assert authors[0].info == info
    assert authors[0].locked_posts == {}
    assert list(scan_posts(root, authors[0])) == []
    source = next(scan_posts(root, authors[1]))
    assert source.post.overview.post == record.post
    assert source.post.overview.access is PostAccess.locked
    assert source.post.record is None
    assert source.post.folder is None
    assert source.marks == PostMarks()
    assert source.record_fingerprint is None
    assert source.marks_fingerprint is None


def test_locked_metadata_keeps_saved_body_marks_and_same_file_fingerprints(
    root: Path, record: StoredPost
) -> None:
    folder = _save(root, record)
    store = JsonPostStore(root)
    info = AuthorInfo('writer', LATER, title='Author title')
    store.save_author(info)
    locked = LockedPost(replace(record.post, title='Latest title'), LATER)
    store.save_locked_post(locked)
    marks = PostMarks(
        seen_at=NOW, favorite=True, positions={VIDEO_ID: PlaybackPosition(15.5, NOW)}
    )
    JsonPostMarks(root).save_marks('writer', POST_ID, marks)
    original_bytes = (folder / 'post.json').read_bytes()
    author = next(scan_authors(root))
    source = next(scan_posts(root, author))
    assert source.post.overview.post == locked.post
    assert source.post.overview.access is PostAccess.locked
    assert source.post.record == record
    assert source.post.folder == folder.relative_to(root).as_posix()
    assert source.marks == marks
    assert source.record_fingerprint == _fingerprint(folder / 'post.json')
    assert source.marks_fingerprint == _fingerprint(folder / 'viewer.json')
    service = root / 'writer/.boosty-downloader'
    assert author.author_fingerprint == _fingerprint(service / 'author.json')
    assert author.locked_fingerprint == _fingerprint(service / 'locked.json')
    assert (folder / 'post.json').read_bytes() == original_bytes


@pytest.mark.parametrize('saved', [False, True])
def test_scans_return_independent_nested_values(
    root: Path, record: StoredPost, *, saved: bool
) -> None:
    if saved:
        _save(root, record)
    JsonPostStore(root).save_locked_post(LockedPost(record.post, LATER))
    author = next(scan_authors(root))
    expected = deepcopy(author)
    first = next(scan_posts(root, author))
    second = next(scan_posts(root, author))
    first.post.overview.post.tags.append('mutated')
    if first.post.record is not None:
        first.post.record.media[IMAGE_ID].path = 'changed.jpg'
    assert author == expected
    assert second == next(scan_posts(root, expected))


def test_fresh_scan_observes_record_edits_removal_and_locked_clear(
    root: Path, record: StoredPost
) -> None:
    folder = _save(root, record)
    store = JsonPostStore(root)
    store.save_locked_post(LockedPost(record.post, LATER))
    store.clear_locked_post('writer', POST_ID)
    record.post.title = 'Edited saved record'
    store.save_post(folder.relative_to(root).as_posix(), record)
    source = next(scan_posts(root, next(scan_authors(root))))
    assert source.post.overview.access is PostAccess.open
    assert source.post.overview.post.title == 'Edited saved record'
    (folder / 'post.json').unlink()
    assert list(scan_posts(root, next(scan_authors(root)))) == []


def test_full_identity_allows_same_id_for_different_authors(
    root: Path, record: StoredPost
) -> None:
    _save(root, record)
    other = deepcopy(record)
    other.post.author = 'other'
    other.post.title = 'Another author'
    _save(root, other)
    sources = [
        post for author in scan_authors(root) for post in scan_posts(root, author)
    ]
    assert {source.post.overview.post.author for source in sources} == {
        'writer',
        'other',
    }
    assert {source.post.overview.post.id for source in sources} == {POST_ID}


def test_duplicate_full_post_identity_is_visible(
    root: Path, record: StoredPost
) -> None:
    _save(root, record)
    duplicate = root / 'writer/2026-10-25 - Another title (abcdefgh)/post.json'
    _write(duplicate, encode_post_record(record))
    with pytest.raises(AmbiguousPostFolderError):
        list(scan_posts(root, next(scan_authors(root))))


@pytest.mark.parametrize(
    ('folder', 'author'),
    [
        ('2026-10-25 - Wrong prefix (12345678)', 'writer'),
        ('2026-10-25 - Right prefix (abcdefgh)', 'wrong'),
    ],
)
def test_record_identity_must_match_folder(
    root: Path, record: StoredPost, folder: str, author: str
) -> None:
    _write(root / author / folder / 'post.json', encode_post_record(record))
    with pytest.raises(InvalidPostRecordError, match='author and folder'):
        list(scan_posts(root, next(scan_authors(root))))


@pytest.mark.parametrize('filename', ['author.json', 'locked.json'])
def test_author_record_identity_must_match_folder(
    root: Path, record: StoredPost, filename: str
) -> None:
    if filename == 'author.json':
        content = encode_author_record(AuthorInfo('writer', NOW))
    else:
        content = encode_locked_posts('writer', {POST_ID: LockedPost(record.post, NOW)})
    _write(root / 'other/.boosty-downloader' / filename, content)
    with pytest.raises(InvalidAuthorRecordError, match='another author'):
        list(scan_authors(root))


def test_marks_check_full_author_and_post_identity(
    root: Path, record: StoredPost
) -> None:
    folder = _save(root, record)
    (folder / 'viewer.json').write_bytes(
        encode_viewer_record('writer', 'abcdefgh-other', PostMarks())
    )
    with pytest.raises(InvalidViewerRecordError, match='another post'):
        list(scan_posts(root, next(scan_authors(root))))


@pytest.mark.parametrize(
    ('filename', 'expected_error'),
    [('post.json', InvalidPostRecordError), ('viewer.json', InvalidViewerRecordError)],
)
def test_malformed_canonical_post_files_fail_visibly(
    root: Path, record: StoredPost, filename: str, expected_error: type[ValueError]
) -> None:
    folder = _save(root, record)
    (folder / filename).write_bytes(b'not JSON')
    with pytest.raises(expected_error):
        list(scan_posts(root, next(scan_authors(root))))


def test_contained_post_folder_alias_preserves_relative_name(
    root: Path, record: StoredPost
) -> None:
    folder = _save(root, record)
    target = root / '.boosty-downloader/retained'
    target.parent.mkdir(exist_ok=True)
    folder.rename(target)
    _write(target / 'images/cover.jpg', b'cover')
    _symlink(target, folder, directory=True)
    source = next(scan_posts(root, next(scan_authors(root))))
    assert source.post.record == record
    assert source.post.folder == folder.relative_to(root).as_posix()
    assert source.cover_path == f'{source.post.folder}/images/cover.jpg'


@pytest.mark.parametrize('filename', ['post.json', 'viewer.json'])
def test_contained_source_file_alias_is_read(
    root: Path, record: StoredPost, filename: str
) -> None:
    folder = _save(root, record)
    JsonPostMarks(root).save_marks('writer', POST_ID, PostMarks(favorite=True))
    target = root / f'{filename}.target'
    (folder / filename).rename(target)
    _symlink(target, folder / filename)
    source = next(scan_posts(root, next(scan_authors(root))))
    assert source.post.record == record
    assert source.marks.favorite
    fingerprint = (
        source.record_fingerprint
        if filename == 'post.json'
        else source.marks_fingerprint
    )
    assert fingerprint == _fingerprint(target)


@pytest.mark.parametrize('kind', ['author', 'post', 'record'])
def test_sources_cannot_escape_library_root(
    root: Path, tmp_path: Path, record: StoredPost, kind: str
) -> None:
    folder = _save(root, record)
    match kind:
        case 'author':
            link = root / 'writer'
            target = tmp_path / 'outside-author'
        case 'post':
            link = folder
            target = tmp_path / 'outside-post'
        case 'record':
            link = folder / 'post.json'
            target = tmp_path / 'outside.json'
        case _:
            pytest.fail(f'Unexpected link kind: {kind}')
    link.rename(target)
    _symlink(target, link, directory=kind != 'record')
    with pytest.raises(ValueError, match='escapes'):
        [post for author in scan_authors(root) for post in scan_posts(root, author)]


def test_dangling_canonical_source_link_is_not_silently_absent(
    root: Path, record: StoredPost
) -> None:
    folder = _save(root, record)
    (folder / 'post.json').unlink()
    _symlink(root / 'missing.json', folder / 'post.json')
    with pytest.raises(FileNotFoundError):
        list(scan_posts(root, next(scan_authors(root))))


def test_source_io_errors_are_not_reclassified_as_missing(
    root: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _save(root, record)
    original_open = os.open

    def denied(path: str | bytes | Path, flags: int) -> int:
        if Path(os.fsdecode(path)) == folder / 'post.json':
            message = 'cannot read record'
            raise PermissionError(message)
        return original_open(path, flags)

    monkeypatch.setattr(os, 'open', denied)
    with pytest.raises(PermissionError, match='cannot read'):
        list(scan_posts(root, next(scan_authors(root))))


def test_scan_uses_direct_record_reads_and_stats_only_cover_candidates(
    root: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = _save(root, record)
    _write(folder / 'images/cover.jpg', b'cover')
    _write(folder / 'private/nested/unused.bin', b'unrelated media')
    _write(folder / 'post.html', b'not a source')
    _write(root / 'writer/boosty.db', b'legacy cache')
    opened: list[Path] = []
    original_open = os.open
    original_iterdir = Path.iterdir

    def tracked_open(path: str | bytes | Path, flags: int) -> int:
        opened.append(Path(os.fsdecode(path)))
        return original_open(path, flags)

    def shallow_iterdir(path: Path) -> Iterator[Path]:
        assert path in {root, root / 'writer'}
        return original_iterdir(path)

    def forbidden_lookup(*_args: object, **_kwargs: object) -> None:
        pytest.fail('Index source scan must not repeat store lookup for every post')

    monkeypatch.setattr(os, 'open', tracked_open)
    monkeypatch.setattr(Path, 'iterdir', shallow_iterdir)
    monkeypatch.setattr(JsonPostStore, 'find_post', forbidden_lookup)
    source = next(scan_posts(root, next(scan_authors(root))))
    assert source.cover_path == f'{source.post.folder}/images/cover.jpg'
    assert opened == [folder / 'post.json']


@pytest.mark.parametrize('image_state', ['present', 'empty', 'missing', 'linked'])
def test_cover_uses_saved_image_then_first_video_then_locked_teaser(
    root: Path, record: StoredPost, image_state: str
) -> None:
    folder = _save(root, record)
    image = folder / 'images/cover.jpg'
    _write(folder / 'video/preview.jpg', b'preview')
    match image_state:
        case 'present':
            _write(image, b'cover')
        case 'empty':
            _write(image, b'')
        case 'linked':
            image.parent.mkdir(parents=True)
            _symlink(folder / 'video/preview.jpg', image)
        case 'missing':
            pass
        case _:
            pytest.fail(f'Unexpected image state: {image_state}')
    teaser = '.boosty-downloader/teasers/locked.jpg'
    _write(root / 'writer' / teaser, b'teaser')
    JsonPostStore(root).save_locked_post(LockedPost(record.post, LATER, teaser))
    author = next(scan_authors(root))
    source = next(scan_posts(root, author))
    chosen = 'images/cover.jpg' if image_state == 'present' else 'video/preview.jpg'
    assert source.cover_path == f'{source.post.folder}/{chosen}'
    if image.exists() or image.is_symlink():
        image.unlink()
    (folder / 'video/preview.jpg').unlink()
    assert next(scan_posts(root, author)).cover_path == f'writer/{teaser}'


def test_cover_does_not_fall_back_to_second_video(
    root: Path, record: StoredPost
) -> None:
    second_id = 'boosty_video:second'
    record.blocks.append(MediaBlock(second_id))
    record.media[second_id] = replace(
        record.media[VIDEO_ID], position=2, preview_path='video/second.jpg'
    )
    folder = _save(root, record)
    _write(folder / 'video/second.jpg', b'second preview')
    assert next(scan_posts(root, next(scan_authors(root)))).cover_path is None


@pytest.mark.parametrize('filename', ['author.json', 'locked.json'])
def test_malformed_author_service_sources_fail_visibly(
    root: Path, filename: str
) -> None:
    _write(root / 'writer/.boosty-downloader' / filename, b'not JSON')
    with pytest.raises(InvalidAuthorRecordError):
        list(scan_authors(root))


@pytest.mark.parametrize('filename', ['post.json', 'viewer.json'])
def test_canonical_source_must_be_an_ordinary_file(
    root: Path, record: StoredPost, filename: str
) -> None:
    folder = _save(root, record)
    path = folder / filename
    path.unlink(missing_ok=True)
    path.mkdir()
    with pytest.raises(ValueError, match='ordinary file'):
        list(scan_posts(root, next(scan_authors(root))))


def test_a_second_alias_for_the_same_post_is_ambiguous(
    root: Path, record: StoredPost
) -> None:
    folder = _save(root, record)
    alias = folder.parent / '2026-10-25 - Alias (abcdefgh)'
    _symlink(folder, alias, directory=True)
    with pytest.raises(AmbiguousPostFolderError):
        list(scan_posts(root, next(scan_authors(root))))


def test_matching_prefix_does_not_collapse_distinct_full_post_ids(
    root: Path, record: StoredPost
) -> None:
    _save(root, record)
    second = deepcopy(record)
    second.post.id = 'abcdefgh-second'
    _save(root, second)
    sources = list(scan_posts(root, next(scan_authors(root))))
    assert {source.post.overview.post.id for source in sources} == {
        POST_ID,
        second.post.id,
    }


@pytest.mark.skipif(
    os.name == 'nt', reason='Windows normalizes or rejects these folder names'
)
@pytest.mark.parametrize('name', ['notes.', 'backup: old'])
def test_unrelated_nonportable_folder_names_are_not_author_sources(
    root: Path, name: str
) -> None:
    folder = root / name
    folder.mkdir(parents=True)
    assert list(scan_authors(root)) == []
    _write(folder / '.boosty-downloader/notes.txt', b'unrelated service file')
    _write(folder / '2026-10-25 - No record (abcdefgh)/viewer.json', b'not a source')
    assert list(scan_authors(root)) == []


@pytest.mark.skipif(
    os.name == 'nt', reason='Windows normalizes or rejects these folder names'
)
@pytest.mark.parametrize('name', ['notes.', 'backup: old'])
@pytest.mark.parametrize('source', ['author', 'locked', 'post'])
def test_canonical_author_sources_require_portable_folder_names(
    root: Path, record: StoredPost, name: str, source: str
) -> None:
    record.post.author = name
    service = root / name / '.boosty-downloader'
    match source:
        case 'author':
            path = service / 'author.json'
            data = encode_author_record(AuthorInfo(name, NOW))
        case 'locked':
            path = service / 'locked.json'
            data = encode_locked_posts(name, {POST_ID: LockedPost(record.post, NOW)})
        case 'post':
            path = root / name / '2026-10-25 - Saved lesson (abcdefgh)/post.json'
            data = encode_post_record(record)
        case _:
            pytest.fail(f'Unexpected source: {source}')
    _write(path, data)
    with pytest.raises(ValueError, match='portable directory name'):
        list(scan_authors(root))
