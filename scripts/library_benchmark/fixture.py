"""Create and validate an exclusively owned synthetic benchmark library."""

from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from boosty_downloader.domain.stored_post import AuthorInfo, MediaKind, MediaStatus
from boosty_downloader.infrastructure.library._author_json import (
    encode_author_record,
    encode_locked_posts,
)
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.library._post_json import encode_post_record
from boosty_downloader.infrastructure.library._viewer_json import encode_viewer_record
from boosty_downloader.infrastructure.library.library_format import initialize_library
from library_benchmark._fixture_data import (
    BENCHMARK_TAG,
    SEARCH_QUERY,
    SEARCH_TEXT,
    FixtureConfig,
    FixturePost,
    author_name,
    iter_fixture_posts,
)

__all__ = [
    'BENCHMARK_TAG',
    'SEARCH_QUERY',
    'SEARCH_TEXT',
    'FixtureConfig',
    'FixtureDescription',
    'FixtureError',
    'FixturePost',
    'author_name',
    'iter_fixture_posts',
    'prepare_fixture',
]

if TYPE_CHECKING:
    from collections.abc import Iterator

    from boosty_downloader.domain.stored_post import LockedPost

MANIFEST_FILENAME: Final = '.benchmark-fixture.json'
_INDEX_FILES: Final = frozenset(
    f'.boosty-downloader/index.db{suffix}'
    for suffix in ('', '-wal', '-shm', '-journal')
)
_CANONICAL_FILENAMES: Final = frozenset(
    {'post.json', 'viewer.json', 'author.json', 'locked.json'}
)
_COVER_BYTES: Final = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4f4YBAASZAcwPiojEAAAAAElFTkSuQmCC'
)


class FixtureError(ValueError):
    """The supplied directory is not a complete unchanged benchmark fixture."""


@dataclass(frozen=True, slots=True)
class FixtureDescription:
    """Verified fixture dimensions and actual canonical JSON size."""

    root: Path
    config: FixtureConfig
    source_bytes: int
    posts: int
    media: int
    marks: int
    locked: int
    cover_files: int


class _FileFingerprint(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    size: int = Field(ge=0)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class _FixtureManifest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)

    generator: Literal['boosty-library-benchmark']
    format_version: Literal[2]
    complete: Literal[True]
    config: FixtureConfig
    files: dict[str, _FileFingerprint]


def prepare_fixture(root: Path, config: FixtureConfig) -> FixtureDescription:
    """Create a new fixture or validate one completely before any benchmark writes."""
    root = root.parent.resolve() / root.name
    if root.exists() or root.is_symlink():
        manifest = _read_manifest(root, config)
        _verify_files(root, manifest)
    else:
        root.mkdir(parents=True)
        manifest = _generate(root, config)
        _write_manifest(root, manifest)
    return _describe(root, manifest)


def _read_manifest(root: Path, config: FixtureConfig) -> _FixtureManifest:
    _require_directory(root)
    path = root / MANIFEST_FILENAME
    try:
        _require_file(path)
        manifest = _FixtureManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError) as error:
        message = f'Not a complete benchmark fixture: {root}'
        raise FixtureError(message) from error
    if manifest.config != config:
        message = 'Benchmark fixture configuration differs; use a new directory'
        raise FixtureError(message)
    _validate_manifest_paths(manifest)
    return manifest


def _validate_manifest_paths(manifest: _FixtureManifest) -> None:
    for name in manifest.files:
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or '..' in path.parts
            or str(path) != name
            or '\\' in name
            or ':' in name
            or name in _INDEX_FILES
            or name == MANIFEST_FILENAME
        ):
            message = 'Benchmark manifest contains an invalid source path'
            raise FixtureError(message)
    if set(manifest.files) != _expected_paths(manifest.config):
        message = 'Benchmark fixture manifest has an incomplete source inventory'
        raise FixtureError(message)


def _expected_paths(config: FixtureConfig) -> set[str]:
    paths = {'.boosty-downloader/library.json'}
    for post in iter_fixture_posts(config):
        author = post.record.post.author
        paths.update(
            {
                f'{author}/.boosty-downloader/author.json',
                f'{author}/.boosty-downloader/locked.json',
                f'{post.folder}/post.json',
            }
        )
        if post.marks is not None:
            paths.add(f'{post.folder}/viewer.json')
        if cover := _cover_path(post):
            paths.add(f'{post.folder}/{cover}')
    return paths


def _verify_files(root: Path, manifest: _FixtureManifest) -> None:
    expected = set(manifest.files) | {MANIFEST_FILENAME}
    directories = _expected_directories(expected)
    found: set[str] = set()
    for path in _walk_files(root, directories):
        name = path.relative_to(root).as_posix()
        if name in _INDEX_FILES:
            continue
        if name not in expected:
            message = f'Unexpected file in benchmark fixture: {name}'
            raise FixtureError(message)
        found.add(name)
        if (
            name != MANIFEST_FILENAME
            and _fingerprint(path.read_bytes()) != manifest.files[name]
        ):
            message = f'Benchmark fixture source changed: {name}'
            raise FixtureError(message)
    if found != expected:
        message = 'Benchmark fixture is incomplete; use a new directory'
        raise FixtureError(message)


def _expected_directories(files: set[str]) -> set[str]:
    return {
        parent.as_posix() for name in files for parent in PurePosixPath(name).parents
    }


def _walk_files(root: Path, directories: set[str]) -> Iterator[Path]:
    for current, folders, files in os.walk(root, followlinks=False):
        folder = Path(current)
        for name in folders:
            child = folder / name
            _require_directory(child)
            if child.relative_to(root).as_posix() not in directories:
                message = f'Unexpected directory in benchmark fixture: {child}'
                raise FixtureError(message)
        for name in files:
            path = folder / name
            _require_file(path)
            yield path


def _require_directory(path: Path) -> None:
    info = path.lstat()
    if is_link(info) or not S_ISDIR(info.st_mode):
        message = f'Benchmark directory must be an ordinary directory: {path}'
        raise FixtureError(message)


def _require_file(path: Path) -> None:
    info = path.lstat()
    if is_link(info) or not S_ISREG(info.st_mode) or info.st_nlink != 1:
        message = f'Benchmark file must be ordinary and unshared: {path}'
        raise FixtureError(message)


def _fingerprint(data: bytes) -> _FileFingerprint:
    return _FileFingerprint(size=len(data), sha256=hashlib.sha256(data).hexdigest())


def _write_file(
    root: Path, name: str, data: bytes, files: dict[str, _FileFingerprint]
) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)
    files[name] = _fingerprint(data)


def _generate(root: Path, config: FixtureConfig) -> _FixtureManifest:
    initialize_library(root)
    marker = '.boosty-downloader/library.json'
    files = {marker: _fingerprint((root / marker).read_bytes())}
    locked: dict[str, LockedPost] = {}
    current_author: str | None = None
    for post in iter_fixture_posts(config):
        author = post.record.post.author
        if author != current_author:
            if current_author is not None:
                _write_locked(root, current_author, locked, files)
            locked = {}
            current_author = author
            _write_author(root, post, config, files)
        _write_post(root, post, files)
        if post.locked is not None:
            locked[post.record.post.id] = post.locked
    if current_author is not None:
        _write_locked(root, current_author, locked, files)
    return _FixtureManifest(
        generator='boosty-library-benchmark',
        format_version=2,
        complete=True,
        config=config,
        files=files,
    )


def _write_author(
    root: Path,
    post: FixturePost,
    config: FixtureConfig,
    files: dict[str, _FileFingerprint],
) -> None:
    author = post.record.post.author
    info = AuthorInfo(
        author,
        post.record.sync.synced_at,
        title=f'Benchmark {author}',
        owner_name='Synthetic creator',
        description='Offline synthetic library for performance measurements.',
        remote_post_count=config.posts_per_author,
    )
    _write_file(
        root,
        f'{author}/.boosty-downloader/author.json',
        encode_author_record(info),
        files,
    )


def _write_locked(
    root: Path,
    author: str,
    locked: dict[str, LockedPost],
    files: dict[str, _FileFingerprint],
) -> None:
    _write_file(
        root,
        f'{author}/.boosty-downloader/locked.json',
        encode_locked_posts(author, locked),
        files,
    )


def _write_post(
    root: Path, post: FixturePost, files: dict[str, _FileFingerprint]
) -> None:
    _write_file(
        root, f'{post.folder}/post.json', encode_post_record(post.record), files
    )
    if post.marks is not None:
        metadata = post.record.post
        data = encode_viewer_record(metadata.author, metadata.id, post.marks)
        _write_file(root, f'{post.folder}/viewer.json', data, files)
    if cover := _cover_path(post):
        _write_file(root, f'{post.folder}/{cover}', _COVER_BYTES, files)


def _cover_path(post: FixturePost) -> str | None:
    for entry in post.record.media.values():
        if (
            entry.kind is MediaKind.image
            and entry.status is MediaStatus.downloaded
            and entry.removed_at is None
            and entry.path
        ):
            return entry.path
    return None


def _write_manifest(root: Path, manifest: _FixtureManifest) -> None:
    data = (manifest.model_dump_json(indent=2) + '\n').encode()
    with (root / MANIFEST_FILENAME).open('xb') as stream:
        stream.write(data)


def _describe(root: Path, manifest: _FixtureManifest) -> FixtureDescription:
    config = manifest.config
    posts = config.authors * config.posts_per_author
    return FixtureDescription(
        root,
        config,
        sum(
            item.size
            for name, item in manifest.files.items()
            if PurePosixPath(name).name in _CANONICAL_FILENAMES
        ),
        posts,
        posts * 5,
        config.authors * ((config.posts_per_author + 1) // 2),
        config.authors * ((config.posts_per_author + 19) // 20),
        sum('/media/' in name for name in manifest.files),
    )
