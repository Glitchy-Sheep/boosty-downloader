"""Production reader acceptance and ownership checks for generated viewer data."""

from __future__ import annotations

import json
import os
import shutil
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
from stat import (
    FILE_ATTRIBUTE_ARCHIVE,
    FILE_ATTRIBUTE_DIRECTORY,
    FILE_ATTRIBUTE_REPARSE_POINT,
)
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest
from library_sample import manifest
from library_sample.asset_models import AssetBackend, AttachmentType
from library_sample.assets import create_assets
from library_sample.content import AUTHORS, author_counts, iter_posts, post_id
from library_sample.generator import prepare_sample
from library_sample.manifest import MANIFEST_NAME
from library_sample.models import (
    AuthorName,
    SampleConfig,
    SampleDescription,
    SamplePost,
    Scenario,
)

from boosty_downloader.domain.library import PostAccess, PostFilters
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    MediaBlock,
    MediaKind,
    MediaStatus,
    TextBlock,
)
from boosty_downloader.infrastructure.library.reader import JsonLibraryReader

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from os import stat_result
    from pathlib import Path

    from library_sample.asset_models import AssetCatalog


@pytest.fixture(scope='module')
def assets(tmp_path_factory: pytest.TempPathFactory) -> AssetCatalog:
    return create_assets(
        tmp_path_factory.mktemp('sample-assets') / 'assets',
        seed=7,
        backend=AssetBackend.fallback,
    )


@pytest.fixture(scope='module')
def sample(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp('sample-library') / 'library'
    result = prepare_sample(root, SampleConfig(posts=24), backend=AssetBackend.fallback)
    assert result.posts == 24
    assert result.saved_posts == 18
    assert result.locked_posts == 9
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob('*')
        if path.is_file() and not path.name.startswith('index.db')
    }


def test_generated_library_is_readable_without_source_assets_api(sample: Path) -> None:
    reader = JsonLibraryReader(sample)
    reader.prepare()
    assert {item.author for item in reader.authors()} == {
        theme.name for theme in AUTHORS
    }
    statuses: set[MediaStatus] = set()
    kinds: set[MediaKind] = set()
    saved = locked_only = retained_locked = 0
    for author in reader.authors():
        rows = reader.list_posts(author.author, PostFilters())
        assert len(rows) == 8
        for row in rows:
            detail = reader.post(author.author, row.post.id)
            assert detail is not None
            if detail.record is None:
                locked_only += 1
                assert detail.folder is None
                assert detail.overview.access == PostAccess.locked
                continue
            saved += 1
            retained_locked += detail.overview.access == PostAccess.locked
            assert detail.folder is not None
            assert reader.get_marks(author.author, row.post.id) is not None
            for entry in detail.record.media.values():
                statuses.add(entry.status)
                kinds.add(entry.kind)
                assert entry.path is not None
                path = sample / detail.folder / entry.path
                assert path.is_file() == (entry.status == MediaStatus.downloaded)
                if path.is_file():
                    assert path.stat().st_size > 0
    assert (saved, locked_only, retained_locked) == (18, 6, 3)
    assert statuses == set(MediaStatus)
    assert kinds == set(MediaKind)


def test_anchors_cover_links_removed_history_attachments_and_marks(
    assets: AssetCatalog,
) -> None:
    config = SampleConfig(posts=24)
    posts = list(iter_posts(config, assets))
    records = [post.record for post in posts if post.record is not None]
    all_ids = {record.post.id for record in records}
    links = [
        fragment.link_url
        for record in records
        for block in record.blocks
        if isinstance(block, TextBlock)
        for fragment in block.fragments
        if isinstance(fragment, PostDataChunkText.TextFragment) and fragment.link_url
    ]
    assert any(
        post_id(config, AuthorName.devlog.value, Scenario.text_only) in link
        for link in links
    )
    assert any(post_id(config, AuthorName.music.value, 0) in link for link in links)
    assert any(
        post_id(config, AuthorName.devlog.value, Scenario.locked_teaser) in link
        for link in links
    )
    assert post_id(config, AuthorName.devlog.value, 999999) not in all_ids
    assert any(link == 'https://example.org/' for link in links)
    filenames = {
        entry.filename
        for record in records
        for entry in record.media.values()
        if entry.filename
    }
    assert {asset.path.name for asset in assets.attachments} <= filenames
    assert {asset.file_type for asset in assets.attachments} == set(AttachmentType)
    assert any(
        ',' in name
        and ' ' in name
        and any('А' <= character <= 'я' for character in name)
        for name in filenames
    )
    removed = [
        entry
        for record in records
        for entry in record.media.values()
        if entry.removed_at
    ]
    assert {entry.status for entry in removed} == {
        MediaStatus.downloaded,
        MediaStatus.pending,
        MediaStatus.deleted,
    }
    assert (
        sum(entry.status == MediaStatus.downloaded for entry in removed)
        > len(removed) / 2
    )
    for record in records:
        referenced = {
            block.media_id for block in record.blocks if isinstance(block, MediaBlock)
        }
        assert not any(
            entry.removed_at
            for media_id, entry in record.media.items()
            if media_id in referenced
        )
    positions = [
        position
        for post in posts
        if post.marks
        for position in post.marks.positions.values()
    ]
    assert any(
        position.seconds == 0 and position.finished_at is None for position in positions
    )
    assert any(position.seconds > 0 for position in positions)
    assert any(position.finished_at for position in positions)
    assert any(
        post.marks
        and post.marks.seen_at
        and post.record
        and any(
            entry.added_at > post.marks.seen_at for entry in post.record.media.values()
        )
        for post in posts
    )


@pytest.mark.parametrize('count', [1, 2, 23, 24, 25, 1430, 5000])
def test_exact_allocation_and_stable_identity_prefix(
    count: int, assets: AssetCatalog
) -> None:
    config = SampleConfig(posts=count)
    posts = list(iter_posts(config, assets))
    assert len(posts) == count
    identities = [_identity(post) for post in posts]
    assert len(set(identities)) == count
    assert sum(author_counts(config).values()) == count
    if count == 1430:
        assert list(author_counts(config).values()) == [1200, 160, 70]
    smaller = list(iter_posts(replace(config, posts=1), assets))
    assert smaller[0].record is not None
    assert smaller[0].record.post.id in identities


def test_content_does_not_depend_on_asset_backend(assets: AssetCatalog) -> None:
    config = SampleConfig(posts=24)
    other_backend = replace(assets, backend=AssetBackend.ffmpeg)
    assert list(iter_posts(config, assets)) == list(iter_posts(config, other_backend))
    assert list(iter_posts(config, assets)) == list(iter_posts(config, assets))
    changed = list(iter_posts(replace(config, seed=8), assets))
    assert changed != list(iter_posts(config, assets))


def test_realistic_sizes_and_author_composition(assets: AssetCatalog) -> None:
    totals: dict[str, Counter[MediaKind]] = {theme.name: Counter() for theme in AUTHORS}
    for post in iter_posts(SampleConfig(), assets):
        if post.record is None:
            continue
        for entry in post.record.media.values():
            if entry.status == MediaStatus.downloaded:
                assert entry.size is not None
                assert entry.size > 0
                totals[post.record.post.author][entry.kind] += entry.size
    devlog, music, art = (totals[name.value] for name in AuthorName)
    assert (
        devlog[MediaKind.boosty_video]
        > devlog[MediaKind.file] + devlog[MediaKind.image]
    )
    assert music[MediaKind.file] > music[MediaKind.audio] + music[MediaKind.image]
    assert (
        art[MediaKind.image] < art[MediaKind.boosty_video] < art[MediaKind.image] * 1.7
    )


def test_reuse_preserves_canonical_bytes_and_mtimes_and_repairs_index(
    sample: Path, tmp_path: Path
) -> None:
    root = tmp_path / 'copy'
    shutil.copytree(sample, root)
    before = _snapshot(root)
    times = {name: (root / name).stat().st_mtime_ns for name in before}
    index = root / '.boosty-downloader/index.db'
    index.write_bytes(b'broken disposable index')
    prepare_sample(root, SampleConfig(posts=24), backend=AssetBackend.fallback)
    assert _snapshot(root) == before
    assert {name: (root / name).stat().st_mtime_ns for name in before} == times
    assert len(JsonLibraryReader(root).authors()) == 3


@pytest.mark.parametrize(
    'change',
    [
        'extra-file',
        'extra-directory',
        'missing',
        'modified',
        'manifest-key',
        'version',
        'bool-version',
        'missing-generator',
        'missing-version',
        'path',
        'index-directory',
        'symlink',
        'index-symlink',
    ],
)
def test_changed_or_unsafe_samples_are_rejected_without_writes(
    sample: Path, tmp_path: Path, change: str
) -> None:
    root = tmp_path / 'copy'
    shutil.copytree(sample, root)
    marker = root / '.boosty-downloader/library.json'
    manifest_path = root / MANIFEST_NAME
    match change:
        case 'extra-file':
            (root / 'extra').write_text('user data', encoding='utf-8')
        case 'extra-directory':
            (root / 'empty').mkdir()
        case 'missing':
            marker.unlink()
        case 'modified':
            marker.write_text('changed', encoding='utf-8')
        case 'index-directory':
            (root / '.boosty-downloader/index.db').unlink()
            (root / '.boosty-downloader/index.db').mkdir()
        case 'symlink' | 'index-symlink':
            path = (
                marker if change == 'symlink' else root / '.boosty-downloader/index.db'
            )
            path.unlink()
            _symlink(path, sample / '.boosty-downloader/library.json')
        case _:
            _tamper_manifest(manifest_path, change)
    before = _snapshot(root)
    with pytest.raises(
        ValueError,
        match=r'Sample|sample|output|manifest|validation|seed|posts|locked-only',
    ):
        prepare_sample(root, SampleConfig(posts=24), backend=AssetBackend.fallback)
    assert _snapshot(root) == before


@pytest.mark.parametrize(
    'config', [SampleConfig(seed=8, posts=24), SampleConfig(posts=25)]
)
def test_changed_arguments_do_not_reset_existing_sample(
    sample: Path, config: SampleConfig
) -> None:
    before = _snapshot(sample)
    with pytest.raises(ValueError, match='different arguments'):
        prepare_sample(sample, config, backend=AssetBackend.fallback)
    assert _snapshot(sample) == before


@pytest.mark.parametrize(
    'existing', ['empty-directory', 'file', 'symlink', 'incomplete']
)
def test_arbitrary_output_is_not_adopted(tmp_path: Path, existing: str) -> None:
    root = tmp_path / 'output'
    match existing:
        case 'file':
            root.write_text('user file', encoding='utf-8')
        case 'symlink':
            _symlink(root, tmp_path)
        case _:
            root.mkdir()
            if existing == 'incomplete':
                (root / '.boosty-downloader').mkdir()
    with pytest.raises(
        ValueError,
        match=r'Sample|sample|output|manifest|validation|seed|posts|locked-only',
    ):
        prepare_sample(root, SampleConfig(posts=1), backend=AssetBackend.fallback)
    assert not (root / MANIFEST_NAME).is_file()


@pytest.mark.parametrize(
    ('seed', 'posts'), [(-1, 1), (2**32, 1), (True, 1), (7, 0), (7, -1), (7, True)]
)
def test_invalid_dimensions_fail_before_writes(seed: int, posts: int) -> None:
    with pytest.raises(
        ValueError,
        match=r'Sample|sample|output|manifest|validation|seed|posts|locked-only',
    ):
        SampleConfig(seed=seed, posts=posts)


def test_locked_only_invariant() -> None:
    with pytest.raises(ValueError, match=r'seed|posts|locked-only'):
        SamplePost(record=None, locked=None, marks=None, files=())


def _identity(post: SamplePost) -> str:
    if post.record is not None:
        return post.record.post.id
    assert post.locked is not None
    return post.locked.post.id


def test_generated_canonical_bytes_are_repeatable(tmp_path: Path) -> None:
    first, second = tmp_path / 'first', tmp_path / 'second'
    for root in (first, second):
        prepare_sample(root, SampleConfig(posts=1), backend=AssetBackend.fallback)
    assert _snapshot(first) == _snapshot(second)


def test_generation_failure_leaves_no_complete_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_assets(*_args: object, **_kwargs: object) -> None:
        message = 'Synthetic asset failure'
        raise RuntimeError(message)

    monkeypatch.setattr('library_sample.generator.create_assets', fail_assets)
    root = tmp_path / 'failed'
    with pytest.raises(RuntimeError, match='asset failure'):
        prepare_sample(root, SampleConfig(posts=1))
    assert root.is_dir()
    assert not (root / MANIFEST_NAME).exists()
    with pytest.raises(ValueError, match='not a complete owned sample'):
        prepare_sample(root, SampleConfig(posts=1))


def _tamper_manifest(path: Path, change: str) -> None:
    document = json.loads(path.read_text(encoding='utf-8'))
    match change:
        case 'manifest-key':
            document['unknown'] = True
        case 'version':
            document['version'] = 2
        case 'bool-version':
            document['version'] = True
        case 'missing-generator' | 'missing-version':
            document.pop(change.removeprefix('missing-'))
        case _:
            document['inventory']['files']['../outside'] = next(
                iter(document['inventory']['files'].values())
            )
    path.write_text(json.dumps(document), encoding='utf-8')


def test_increasing_count_never_removes_an_existing_identity(
    assets: AssetCatalog,
) -> None:
    before = {_identity(post) for post in iter_posts(SampleConfig(posts=55), assets)}
    after = {_identity(post) for post in iter_posts(SampleConfig(posts=56), assets)}
    assert before < after
    previous = dict.fromkeys((theme.name for theme in AUTHORS), 0)
    for count in range(1, 10001):
        current = author_counts(SampleConfig(posts=count))
        assert sum(current.values()) == count
        assert all(current[author] >= old for author, old in previous.items())
        previous = current


def _symlink(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as error:
        if getattr(error, 'winerror', None) == 1314:
            pytest.skip('Windows account cannot create symbolic links')
        raise


@dataclass(frozen=True, slots=True)
class _WindowsDirectoryEntry:
    """Directory enumeration without the identity fields Windows omits."""

    name: str
    path: str
    info: stat_result

    def stat(self, *, follow_symlinks: bool = True) -> stat_result:
        del follow_symlinks
        return cast(
            'stat_result',
            SimpleNamespace(
                st_mode=self.info.st_mode,
                st_size=self.info.st_size,
                st_ino=0,
                st_dev=0,
                st_nlink=0,
                st_file_attributes=FILE_ATTRIBUTE_ARCHIVE,
            ),
        )


def test_manifest_refreshes_windows_directory_entry_identity(
    sample: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scandir = os.scandir

    @contextmanager
    def windows_scandir(
        folder: Path,
    ) -> Generator[Iterator[_WindowsDirectoryEntry], None, None]:
        with scandir(folder) as entries:
            rows = [
                _WindowsDirectoryEntry(
                    entry.name, entry.path, entry.stat(follow_symlinks=False)
                )
                for entry in entries
            ]
        yield iter(rows)

    monkeypatch.setattr(manifest.os, 'scandir', windows_scandir)
    result = manifest.inspect_sample(
        sample, SampleConfig(posts=24), AssetBackend.fallback
    )
    assert result is not None
    assert result.posts == 24


def _minimal_description(root: Path) -> SampleDescription:
    return SampleDescription(
        root=root,
        config=SampleConfig(posts=1),
        backend=AssetBackend.fallback,
        authors=1,
        posts=1,
        saved_posts=1,
        locked_posts=0,
        media=0,
    )


@pytest.mark.parametrize(
    ('directory', 'attributes', 'rejected'),
    [
        (False, FILE_ATTRIBUTE_ARCHIVE, False),
        (True, FILE_ATTRIBUTE_DIRECTORY, False),
        (False, FILE_ATTRIBUTE_ARCHIVE | FILE_ATTRIBUTE_REPARSE_POINT, True),
        (True, FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT, True),
    ],
)
def test_manifest_preserves_windows_attribute_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    directory: bool,
    attributes: int,
    rejected: bool,
) -> None:
    root = tmp_path / 'library'
    root.mkdir()
    target = root / 'target'
    if directory:
        target.mkdir()
        (target / 'piece.bin').write_bytes(b'ordinary bytes')
    else:
        target.write_bytes(b'ordinary bytes')
    path_type = type(target)
    lstat = path_type.lstat

    def windows_lstat(path: Path) -> stat_result:
        info = lstat(path)
        if path != target:
            return info
        return cast(
            'stat_result',
            SimpleNamespace(
                st_mode=info.st_mode,
                st_size=info.st_size,
                st_ino=info.st_ino,
                st_dev=info.st_dev,
                st_file_attributes=attributes,
            ),
        )

    monkeypatch.setattr(path_type, 'lstat', windows_lstat)
    if rejected:
        with pytest.raises(ValueError, match='symlink or unexpected file type'):
            manifest.publish_manifest(_minimal_description(root))
        assert not (root / MANIFEST_NAME).exists()
    else:
        manifest.publish_manifest(_minimal_description(root))
        assert (
            manifest.inspect_sample(root, SampleConfig(posts=1), AssetBackend.fallback)
            is not None
        )


def test_manifest_still_rejects_replacement_after_lstat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / 'library'
    root.mkdir()
    target = root / 'piece.bin'
    target.write_bytes(b'original')
    replacement = tmp_path / 'replacement.bin'
    replacement.write_bytes(b'replaced')
    original_open = os.open

    def replace_before_open(
        path: Path, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        if path == target:
            replacement.replace(target)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(manifest.os, 'open', replace_before_open)
    with pytest.raises(ValueError, match='symlink or unexpected file type'):
        manifest.publish_manifest(_minimal_description(root))
    assert not (root / MANIFEST_NAME).exists()
