"""Publish synthetic records through the production store and build their index."""

from __future__ import annotations

import os
import shutil
from pathlib import Path, PurePosixPath
from stat import S_ISREG

from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore
from library_sample.asset_models import AssetBackend
from library_sample.assets import create_assets
from library_sample.content import build_authors, iter_posts
from library_sample.manifest import inspect_sample, publish_manifest
from library_sample.models import (
    AssetPlacement,
    SampleConfig,
    SampleDescription,
    SamplePost,
)


def prepare_sample(
    root: Path, config: SampleConfig, *, backend: AssetBackend = AssetBackend.auto
) -> SampleDescription:
    """Create an absent library or verify and reuse exactly matching owned output."""
    root = Path(os.path.abspath(root))  # noqa: PTH100 - linked ancestors must remain visible to validation
    existing = inspect_sample(root, config, backend)
    if existing is not None:
        LibraryIndex(root).synchronize()
        return existing
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir()
    initialize_library(root)
    return _generate(root, config, backend)


def _generate(
    root: Path, config: SampleConfig, backend: AssetBackend
) -> SampleDescription:
    assets = create_assets(
        root / '.boosty-downloader' / 'sample-assets', seed=config.seed, backend=backend
    )
    store, marks = JsonPostStore(root), JsonPostMarks(root)
    authors = build_authors(config, assets)
    for author in authors:
        store.save_author(author.info)
        _place_files(root / author.info.author, author.files)
    saved = locked = media = 0
    for post in iter_posts(config, assets):
        _save_post(root, store, marks, post)
        saved += post.record is not None
        locked += post.locked is not None
        media += len(post.record.media) if post.record else 0
    LibraryIndex(root).rebuild()
    result = SampleDescription(
        root, config, assets.backend, len(authors), config.posts, saved, locked, media
    )
    publish_manifest(result)
    return result


def _save_post(
    root: Path, store: JsonPostStore, marks: JsonPostMarks, post: SamplePost
) -> None:
    if post.record is not None:
        folder = store.choose_post_folder(post.record.post)
        store.save_post(folder, post.record)
        _place_files(root / folder, post.files)
        _place_files(root / post.record.post.author, post.author_files)
        if post.marks is not None:
            marks.save_marks(post.record.post.author, post.record.post.id, post.marks)
    if post.locked is not None:
        store.save_locked_post(post.locked)


def _place_files(folder: Path, files: tuple[AssetPlacement, ...]) -> None:
    for placement in files:
        relative = PurePosixPath(placement.relative_path)
        if (
            relative.is_absolute()
            or '..' in relative.parts
            or relative.as_posix() != placement.relative_path
        ):
            message = f'Invalid sample asset destination: {placement.relative_path!r}'
            raise ValueError(message)
        if not S_ISREG(placement.source.lstat().st_mode):
            message = f'Sample source must be an ordinary file: {placement.source}'
            raise ValueError(message)
        destination = folder / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(placement.source, destination)
        except OSError:
            with (
                destination.open('xb') as output,
                placement.source.open('rb') as source,
            ):
                shutil.copyfileobj(source, output)
