"""Synthetic fixtures stay deterministic and never adopt existing user libraries."""

from __future__ import annotations

import json
import os
import struct
import zlib
from collections import Counter
from pathlib import Path
from typing import Literal

import pytest
from library_benchmark.fixture import (
    MANIFEST_FILENAME,
    FixtureConfig,
    FixtureError,
    iter_fixture_posts,
    prepare_fixture,
)

from boosty_downloader.domain.stored_post import MediaKind, MediaStatus
from boosty_downloader.infrastructure.library._post_json import decode_post_record
from boosty_downloader.infrastructure.library._viewer_json import decode_viewer_record
from boosty_downloader.infrastructure.library.index import LibraryIndex


@pytest.fixture
def config() -> FixtureConfig:
    return FixtureConfig(authors=2, posts_per_author=4)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob('*')
        if path.is_file()
    }


def test_fixture_is_deterministic_and_sources_use_production_codecs(
    tmp_path: Path, config: FixtureConfig
) -> None:
    first = prepare_fixture(tmp_path / 'first', config)
    second = prepare_fixture(tmp_path / 'second', config)
    assert _snapshot(first.root) == _snapshot(second.root)
    assert first.posts == 8
    assert first.media == 40
    assert first.marks == 4
    assert first.locked == 2
    for post in iter_fixture_posts(config):
        folder = first.root / post.folder
        assert decode_post_record((folder / 'post.json').read_bytes()) == post.record
        if post.marks is not None:
            metadata = post.record.post
            assert (
                decode_viewer_record(
                    (folder / 'viewer.json').read_bytes(),
                    author=metadata.author,
                    post_id=metadata.id,
                )
                == post.marks
            )
    canonical_names = {'post.json', 'viewer.json', 'author.json', 'locked.json'}
    assert first.source_bytes == sum(
        len(data)
        for name, data in _snapshot(first.root).items()
        if Path(name).name in canonical_names
    )


def test_fixture_reuse_leaves_sources_and_mtimes_unchanged(
    tmp_path: Path, config: FixtureConfig
) -> None:
    root = tmp_path / 'library'
    first = prepare_fixture(root, config)
    LibraryIndex(root).rebuild()
    before = _snapshot(root)
    times = {path: path.stat().st_mtime_ns for path in root.rglob('*')}
    assert prepare_fixture(root, config) == first
    assert _snapshot(root) == before
    assert {path: path.stat().st_mtime_ns for path in times} == times


@pytest.mark.parametrize('with_file', [False, True])
def test_existing_directory_is_never_adopted(
    tmp_path: Path, config: FixtureConfig, *, with_file: bool
) -> None:
    root = tmp_path / 'library'
    root.mkdir()
    if with_file:
        (root / 'post.json').write_text('user content')
    before = _snapshot(root)
    with pytest.raises(FixtureError, match='complete benchmark fixture'):
        prepare_fixture(root, config)
    assert _snapshot(root) == before


def test_changed_configuration_is_rejected_without_writes(
    tmp_path: Path, config: FixtureConfig
) -> None:
    root = tmp_path / 'library'
    prepare_fixture(root, config)
    before = _snapshot(root)
    with pytest.raises(FixtureError, match='configuration differs'):
        prepare_fixture(root, FixtureConfig(authors=1, posts_per_author=8))
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        pytest.param('complete', None, id='missing-complete'),
        pytest.param('complete', False, id='unfinished'),
        pytest.param('format_version', 1, id='version'),
        pytest.param('files', {}, id='missing-inventory'),
        pytest.param('unexpected', True, id='unknown-field'),
    ],
)
def test_incomplete_or_unknown_manifest_is_rejected(
    tmp_path: Path, config: FixtureConfig, field: str, value: object
) -> None:
    root = tmp_path / 'library'
    prepare_fixture(root, config)
    path = root / MANIFEST_FILENAME
    document = json.loads(path.read_bytes())
    if value is None:
        document.pop(field)
    else:
        document[field] = value
    path.write_text(json.dumps(document))
    before = _snapshot(root)
    with pytest.raises(FixtureError):
        prepare_fixture(root, config)
    assert _snapshot(root) == before


@pytest.mark.parametrize('contents', ['{broken', '[]', 'null'])
def test_malformed_manifest_is_rejected(
    tmp_path: Path, config: FixtureConfig, contents: str
) -> None:
    root = tmp_path / 'library'
    prepare_fixture(root, config)
    (root / MANIFEST_FILENAME).write_text(contents)
    before = _snapshot(root)
    with pytest.raises(FixtureError):
        prepare_fixture(root, config)
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    'change', ['missing', 'changed', 'extra-file', 'extra-directory']
)
def test_fixture_inventory_changes_are_rejected(
    tmp_path: Path,
    config: FixtureConfig,
    change: Literal['missing', 'changed', 'extra-file', 'extra-directory'],
) -> None:
    root = tmp_path / 'library'
    prepare_fixture(root, config)
    post = next(iter_fixture_posts(config))
    source = root / post.folder / 'post.json'
    match change:
        case 'missing':
            source.unlink()
        case 'changed':
            source.write_bytes(source.read_bytes() + b' ')
        case 'extra-file':
            (root / 'personal-note.txt').write_text('keep')
        case 'extra-directory':
            (root / 'personal-directory').mkdir()
    before = _snapshot(root)
    with pytest.raises(FixtureError):
        prepare_fixture(root, config)
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    'name', ['../outside', '/outside', 'a\\b', 'a:stream', 'a/./b']
)
def test_manifest_paths_cannot_escape_or_use_nonportable_spellings(
    tmp_path: Path, config: FixtureConfig, name: str
) -> None:
    root = tmp_path / 'library'
    prepare_fixture(root, config)
    manifest = root / MANIFEST_FILENAME
    document = json.loads(manifest.read_bytes())
    fingerprint = next(iter(document['files'].values()))
    document['files'][name] = fingerprint
    manifest.write_text(json.dumps(document))
    before = _snapshot(root)
    with pytest.raises(FixtureError, match='invalid source path'):
        prepare_fixture(root, config)
    assert _snapshot(root) == before


@pytest.mark.parametrize('target', ['manifest', 'source', 'index'])
def test_hardlinked_files_are_rejected(
    tmp_path: Path,
    config: FixtureConfig,
    target: Literal['manifest', 'source', 'index'],
) -> None:
    root = tmp_path / 'library'
    prepare_fixture(root, config)
    source = root / next(iter_fixture_posts(config)).folder / 'post.json'
    match target:
        case 'manifest':
            source = root / MANIFEST_FILENAME
        case 'index':
            source = root / '.boosty-downloader' / 'index.db'
            source.write_bytes(b'index placeholder')
        case 'source':
            pass
    external = tmp_path / 'shared'
    os.link(source, external)
    before = source.read_bytes()
    with pytest.raises(FixtureError, match='ordinary and unshared'):
        prepare_fixture(root, config)
    assert source.read_bytes() == external.read_bytes() == before


@pytest.mark.parametrize('target', ['root', 'author', 'source'])
def test_symlinks_are_rejected(
    tmp_path: Path, config: FixtureConfig, target: Literal['root', 'author', 'source']
) -> None:
    root = tmp_path / 'library'
    prepare_fixture(root, config)
    post = next(iter_fixture_posts(config))
    source = root
    match target:
        case 'author':
            source = root / post.record.post.author
        case 'source':
            source = root / post.folder / 'post.json'
        case 'root':
            pass
    external = tmp_path / 'original'
    is_directory = source.is_dir()
    source.rename(external)
    try:
        source.symlink_to(external, target_is_directory=is_directory)
    except OSError as error:
        external.rename(source)
        pytest.skip(f'Symlinks unavailable: {error}')
    with pytest.raises(FixtureError, match='ordinary'):
        prepare_fixture(root, config)


def test_rich_fixture_has_requested_status_history_and_viewing_mix() -> None:
    config = FixtureConfig(authors=1, posts_per_author=1000)
    posts = list(iter_fixture_posts(config))
    entries = [entry for post in posts for entry in post.record.media.values()]
    statuses = Counter(entry.status for entry in entries)
    assert len(entries) == 5000
    assert statuses[MediaStatus.downloaded] == 4000
    assert all(
        statuses[status] == 250
        for status in MediaStatus
        if status is not MediaStatus.downloaded
    )
    removed = [entry for entry in entries if entry.removed_at is not None]
    assert 45 <= len(removed) <= 55
    assert any(entry.status is MediaStatus.downloaded for entry in removed)
    assert any(entry.status is not MediaStatus.downloaded for entry in removed)
    assert sum(post.marks is not None for post in posts) == 500
    assert sum(post.locked is not None for post in posts) == 50
    assert any(post.marks and post.marks.favorite for post in posts)
    assert any(
        post.marks and any(mark.finished_at for mark in post.marks.positions.values())
        for post in posts
    )
    assert {entry.kind for entry in entries} == set(MediaKind)
    assert all(entry.size and entry.path for entry in entries)


@pytest.mark.parametrize(
    'filename', ['viewer.json', 'author.json', 'locked.json', 'library.json']
)
def test_manifest_cannot_hide_missing_nonpost_sources(
    tmp_path: Path, config: FixtureConfig, filename: str
) -> None:
    root = tmp_path / 'library'
    prepare_fixture(root, config)
    path = root / MANIFEST_FILENAME
    document = json.loads(path.read_bytes())
    name = next(name for name in document['files'] if Path(name).name == filename)
    del document['files'][name]
    (root / name).unlink()
    path.write_text(json.dumps(document))
    before = _snapshot(root)
    with pytest.raises(FixtureError, match='incomplete source inventory'):
        prepare_fixture(root, config)
    assert _snapshot(root) == before


def test_cover_payload_is_a_valid_one_pixel_png(
    tmp_path: Path, config: FixtureConfig
) -> None:
    fixture = prepare_fixture(tmp_path / 'library', config)
    covers = list(fixture.root.glob('*/*/media/*'))
    assert covers
    data = covers[0].read_bytes()
    assert data[:8] == b'\x89PNG\r\n\x1a\n'
    offset = 8
    chunks: dict[bytes, bytes] = {}
    while offset < len(data):
        length = int.from_bytes(data[offset : offset + 4], 'big')
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        checksum = int.from_bytes(
            data[offset + 8 + length : offset + 12 + length], 'big'
        )
        assert zlib.crc32(kind + payload) == checksum
        chunks[kind] = payload
        offset += 12 + length
    assert struct.unpack('>2I5B', chunks[b'IHDR']) == (1, 1, 8, 2, 0, 0, 0)
    assert zlib.decompress(chunks[b'IDAT']) == b'\x00\xff\xcc\x00'
    assert chunks[b'IEND'] == b''


def test_external_video_identities_contain_stable_urls():
    posts = list(iter_fixture_posts(FixtureConfig(authors=1, posts_per_author=2)))
    identities = [
        key
        for post in posts
        for key, entry in post.record.media.items()
        if entry.kind is MediaKind.external_video
    ]
    assert identities
    assert all(
        key.startswith('external_video:https://example.test/watch/')
        for key in identities
    )
