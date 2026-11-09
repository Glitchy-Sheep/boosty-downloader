"""Verify ownership before reusing synthetic output, without adopting other files."""

from __future__ import annotations

import hashlib
import os
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

from boosty_downloader.infrastructure.library._atomic_write import write_atomically
from boosty_downloader.infrastructure.library._media_paths import is_link
from library_sample.asset_models import AssetBackend
from library_sample.models import SampleConfig, SampleDescription

if TYPE_CHECKING:
    from collections.abc import Generator
    from os import stat_result
    from typing import BinaryIO

MANIFEST_NAME = '.sample-library.json'
_INDEX_FILES = frozenset(
    f'.boosty-downloader/index.db{suffix}'
    for suffix in ('', '-wal', '-shm', '-journal')
)


class _Fingerprint(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')


class _Inventory(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    files: dict[str, _Fingerprint]
    directories: list[str]


class _Manifest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    generator: Literal['boosty-viewer-sample']
    version: int = Field(ge=1, le=1)
    seed: int = Field(ge=0, le=0xFFFFFFFF)
    posts: int = Field(gt=0)
    backend: AssetBackend
    authors: int = Field(gt=0)
    saved_posts: int = Field(ge=0)
    locked_posts: int = Field(ge=0)
    media: int = Field(ge=0)
    inventory: _Inventory


def check_output_path(root: Path) -> None:
    """Reject linked output ancestors before any ownership check or directory write."""
    for candidate in (root, *root.parents):
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if is_link(info):
            message = f'Sample output cannot follow a symlink: {candidate}'
            raise ValueError(message)


def inspect_sample(
    root: Path, config: SampleConfig, backend: AssetBackend
) -> SampleDescription | None:
    """Return a verified unchanged sample, or None for an absent destination."""
    check_output_path(root)
    if not root.exists():
        return None
    inventory = _inventory(root)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        message = f'Existing output is not a complete owned sample: {root}'
        raise ValueError(message)
    with _open_regular_file(manifest_path, manifest_path.lstat()) as source:
        manifest = _Manifest.model_validate_json(source.read())
    _validate_manifest(manifest, config, backend)
    if inventory != manifest.inventory:
        message = f'Sample files changed; choose a fresh --out: {root}'
        raise ValueError(message)
    return SampleDescription(
        root,
        config,
        manifest.backend,
        manifest.authors,
        manifest.posts,
        manifest.saved_posts,
        manifest.locked_posts,
        manifest.media,
    )


def _validate_manifest(
    manifest: _Manifest, config: SampleConfig, backend: AssetBackend
) -> None:
    if manifest.seed != config.seed or manifest.posts != config.posts:
        message = 'Existing sample uses different arguments; choose a fresh --out'
        raise ValueError(message)
    if manifest.backend == AssetBackend.auto or backend not in {
        AssetBackend.auto,
        manifest.backend,
    }:
        message = 'Existing sample uses a different asset backend; choose a fresh --out'
        raise ValueError(message)
    for relative in (*manifest.inventory.files, *manifest.inventory.directories):
        path = PurePosixPath(relative)
        if (
            not relative
            or path.is_absolute()
            or path.as_posix() != relative
            or '..' in path.parts
            or '\\' in relative
            or ':' in relative
        ):
            message = f'Invalid manifest path: {relative!r}'
            raise ValueError(message)


def publish_manifest(description: SampleDescription) -> None:
    """Publish ownership only after the canonical sample and index are complete."""
    manifest = _Manifest(
        generator='boosty-viewer-sample',
        version=1,
        seed=description.config.seed,
        posts=description.posts,
        backend=description.backend,
        authors=description.authors,
        saved_posts=description.saved_posts,
        locked_posts=description.locked_posts,
        media=description.media,
        inventory=_inventory(description.root),
    )
    write_atomically(
        description.root / MANIFEST_NAME,
        (manifest.model_dump_json(indent=2) + '\n').encode(),
    )


def _inventory(root: Path) -> _Inventory:
    if not S_ISDIR(root.lstat().st_mode):
        message = f'Sample output must be an ordinary directory: {root}'
        raise ValueError(message)
    files: dict[str, _Fingerprint] = {}
    directories: list[str] = []
    _scan_directory(root, root, files, directories)
    return _Inventory(files=files, directories=sorted(directories))


def _scan_directory(
    root: Path, folder: Path, files: dict[str, _Fingerprint], directories: list[str]
) -> None:
    if folder.resolve() != folder:
        _reject_special(folder)
    with os.scandir(folder) as entries:
        children = sorted(entries, key=lambda entry: entry.name)
    for entry in children:
        path = Path(entry.path)
        relative = path.relative_to(root).as_posix()
        info = entry.stat(follow_symlinks=False)
        if is_link(info):
            _reject_special(path)
        if S_ISDIR(info.st_mode):
            if relative == MANIFEST_NAME or relative in _INDEX_FILES:
                _reject_special(path)
            directories.append(relative)
            _scan_directory(root, path, files, directories)
        elif S_ISREG(info.st_mode):
            if relative != MANIFEST_NAME and relative not in _INDEX_FILES:
                files[relative] = _fingerprint(path, info)
        else:
            _reject_special(path)


def _reject_special(path: Path) -> None:
    message = f'Sample contains a symlink or unexpected file type: {path}'
    raise ValueError(message)


@contextmanager
def _open_regular_file(
    path: Path, expected: stat_result
) -> Generator[BinaryIO, None, None]:
    if path.resolve() != path or is_link(expected) or not S_ISREG(expected.st_mode):
        _reject_special(path)
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, 'rb') as source:
        actual = os.fstat(source.fileno())
        if not S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (
            expected.st_dev,
            expected.st_ino,
        ):
            _reject_special(path)
        yield source


def _fingerprint(path: Path, expected: stat_result) -> _Fingerprint:
    digest = hashlib.sha256()
    with _open_regular_file(path, expected) as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return _Fingerprint(size=expected.st_size, sha256=digest.hexdigest())
