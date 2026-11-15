"""Canonical media, playback and large-grid fixtures for isolated browser checks."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from library_sample.asset_models import AssetBackend, AssetCatalog, ImageAsset
from library_sample.assets import create_assets

from boosty_downloader.domain.library_marks import PlaybackPosition, PostMarks
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    AuthorInfo,
    Block,
    LockedPost,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.library.index import LibraryIndex
from boosty_downloader.infrastructure.library.library_format import initialize_library
from boosty_downloader.infrastructure.library.post_marks import JsonPostMarks
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

AUTHOR = 'media_checks'
GALLERY = 'gallery_checks'
REMOVED = 'removed_checks'
EQUAL = 'equal_checks'
SEEN_POST = 3
UPDATED_POST = 4
LOCKED_POST = 5
EQUAL_CURRENT_PHOTOS = 8
EQUAL_CURRENT_VIDEOS = 2
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
Fragment = PostDataChunkText.TextFragment


@dataclass(frozen=True, slots=True)
class Piece:
    """One canonical entry and the immutable asset copied to its post folder."""

    key: str
    entry: MediaEntry
    source: Path | None
    thumbnail: Path | None = None


def post_id(number: int) -> str:
    """Use stable full identities shared with browser assertions."""
    return f'40000000-0000-4000-8000-{number:012d}'


def _metadata(author: str, number: int) -> PostMetadata:
    created = NOW - timedelta(days=number)
    return PostMetadata(
        post_id(number),
        author,
        f'https://boosty.to/{author}/posts/{post_id(number)}',
        f'Media post {number:02d}',
        created,
        created,
        tags=['media', f'post-{number}'],
    )


@dataclass(frozen=True, slots=True)
class PieceOptions:
    """Optional presentation state for one downloaded fixture piece."""

    removed: bool = False
    duration: timedelta | None = None
    thumbnail: Path | None = None


DEFAULT_OPTIONS = PieceOptions()
PREVIEW_DIRECTORY = Path(__file__).with_name('viewer_media_assets')


def _with_grid_previews(assets: AssetCatalog) -> AssetCatalog:
    """Use 480px JPEG previews sampled from the same three large PNG originals."""
    images: list[ImageAsset] = []
    for index, image in enumerate(assets.images[:3]):
        name = f'preview-{index}.jpg'
        thumbnail = image.path.with_name(name)
        shutil.copyfile(PREVIEW_DIRECTORY / name, thumbnail)
        images.append(replace(image, thumbnail_path=thumbnail))
    return replace(assets, images=tuple(images))


def _piece(
    kind: MediaKind,
    name: str,
    position: int,
    source: Path,
    options: PieceOptions = DEFAULT_OPTIONS,
) -> Piece:
    filename = f"{name} !'() # 100%25{source.suffix}"
    entry = MediaEntry(
        kind,
        MediaStatus.downloaded,
        NOW - timedelta(days=1),
        position,
        removed_at=NOW if options.removed else None,
        path=f'media/{filename}',
        size=source.stat().st_size,
        title=name,
        filename=filename,
        duration=options.duration,
    )
    if kind is MediaKind.audio:
        entry.artist = 'Fixture orchestra'
    return Piece(f'{kind.value}:{name}', entry, source, options.thumbnail)


def _mixed(assets: AssetCatalog, number: int, *, removed_only: bool) -> list[Piece]:
    pieces = [
        _piece(
            MediaKind.image,
            f'Photo {number:02d} A',
            0,
            assets.images[0].path,
            PieceOptions(thumbnail=assets.images[0].thumbnail_path),
        ),
        _piece(MediaKind.image, f'Photo {number:02d} B', 1, assets.images[1].path),
        _piece(
            MediaKind.boosty_video,
            f'Video {number:02d}',
            2,
            assets.videos[0].path,
            PieceOptions(duration=assets.videos[0].duration),
        ),
        _piece(
            MediaKind.audio,
            f'Track {number:02d} A',
            3,
            assets.audio[0].path,
            PieceOptions(duration=assets.audio[0].duration),
        ),
        _piece(
            MediaKind.audio,
            f'Track {number:02d} B',
            4,
            assets.audio[1].path,
            PieceOptions(duration=assets.audio[1].duration),
        ),
        _piece(MediaKind.file, f'Notes {number:02d}', 5, assets.attachments[0].path),
        _piece(
            MediaKind.image,
            f'Retained photo {number:02d}',
            6,
            assets.images[2].path,
            PieceOptions(removed=True, thumbnail=assets.images[2].thumbnail_path),
        ),
        _piece(
            MediaKind.external_video,
            f'Retained video {number:02d}',
            7,
            assets.videos[0].path,
            PieceOptions(removed=True, duration=assets.videos[0].duration),
        ),
        _piece(
            MediaKind.audio,
            f'Retained track {number:02d}',
            8,
            assets.audio[0].path,
            PieceOptions(removed=True, duration=assets.audio[0].duration),
        ),
        _piece(
            MediaKind.file,
            f'Retained notes {number:02d}',
            9,
            assets.attachments[0].path,
            PieceOptions(removed=True),
        ),
    ]
    if removed_only:
        for piece in pieces:
            piece.entry.removed_at = NOW
        return pieces
    for position, kind in enumerate(
        (MediaKind.image, MediaKind.boosty_video, MediaKind.audio, MediaKind.file), 10
    ):
        pieces.append(
            Piece(
                f'{kind.value}:missing',
                MediaEntry(kind, MediaStatus.pending, NOW, position),
                None,
            )
        )
    return pieces


def _blocks(pieces: list[Piece]) -> list[Block]:
    blocks: list[Block] = []
    for number in range(20):
        blocks.extend(
            [
                TextBlock([Fragment(f'Needle reading paragraph {number + 1}. ' * 8)]),
                ParagraphBreak(),
            ]
        )
    blocks.extend(
        MediaBlock(piece.key) for piece in pieces if not piece.entry.removed_at
    )
    return blocks


def _equal_rows(assets: AssetCatalog) -> list[Piece]:
    pieces: list[Piece] = []
    for index in range(14):
        pieces.append(
            _piece(
                MediaKind.image,
                f'Equal photo {index}',
                index,
                assets.images[0].path,
                PieceOptions(
                    removed=index >= EQUAL_CURRENT_PHOTOS,
                    thumbnail=assets.images[0].thumbnail_path,
                ),
            )
        )
        pieces.append(
            _piece(
                MediaKind.boosty_video,
                f'Equal video {index}',
                index + 14,
                assets.videos[0].path,
                PieceOptions(
                    removed=index >= EQUAL_CURRENT_VIDEOS,
                    duration=assets.videos[0].duration,
                ),
            )
        )
    for index, kind in enumerate((MediaKind.image, MediaKind.boosty_video), 28):
        pieces.append(
            Piece(
                f'{kind.value}:missing',
                MediaEntry(kind, MediaStatus.pending, NOW, index),
                None,
            )
        )
    return pieces


def _link(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.link(source, destination)


def _save(root: Path, author: str, number: int, pieces: list[Piece]) -> None:
    store, marks = JsonPostStore(root), JsonPostMarks(root)
    metadata = _metadata(author, number)
    folder = store.choose_post_folder(metadata)
    for piece in pieces:
        if piece.source and piece.entry.path:
            _link(piece.source, root / folder / piece.entry.path)
        if piece.thumbnail:
            name = f'{metadata.id}-{piece.entry.position}{piece.thumbnail.suffix}'
            piece.entry.thumbnail_path = f'.boosty-downloader/thumbs/{name}'
            _link(piece.thumbnail, root / author / piece.entry.thumbnail_path)
    store.save_post(
        folder,
        StoredPost(
            metadata,
            PostSync(NOW, NOW),
            _blocks(pieces),
            {piece.key: piece.entry for piece in pieces},
        ),
    )
    if author == AUTHOR and number == LOCKED_POST:
        store.save_locked_post(LockedPost(metadata, NOW))
    positions = {
        piece.key: PlaybackPosition(7)
        for piece in pieces
        if piece.entry.kind in (MediaKind.audio, MediaKind.boosty_video)
    }
    seen = NOW if number == SEEN_POST else None
    if number == UPDATED_POST:
        seen = NOW - timedelta(days=2)
    completed_track = f'audio:Track {number:02d} B'
    if number == 1 and completed_track in positions:
        positions[completed_track] = PlaybackPosition(0, NOW)
    marks.save_marks(
        author,
        metadata.id,
        PostMarks(seen_at=seen, favorite=number in (1, 2, 4), positions=positions),
    )


def prepare(root: Path, *, photos: int = 2000) -> None:
    """Populate a fresh temporary library; no existing reader corpus is changed."""
    root.mkdir()
    initialize_library(root)
    assets = _with_grid_previews(
        create_assets(
            root / '.boosty-downloader' / 'media-assets',
            seed=57,
            backend=AssetBackend.fallback,
        )
    )
    store = JsonPostStore(root)
    for author, title in (
        (AUTHOR, 'Media Checks'),
        (GALLERY, 'Gallery Checks'),
        (REMOVED, 'Removed Checks'),
        (EQUAL, 'Equal Row Checks'),
    ):
        store.save_author(AuthorInfo(author, NOW, title=title))
    for number in range(1, 7):
        _save(root, AUTHOR, number, _mixed(assets, number, removed_only=False))
    _save(root, REMOVED, 1, _mixed(assets, 1, removed_only=True))
    _save(root, EQUAL, 1, _equal_rows(assets))
    for start in range(0, photos, 100):
        pieces = [
            _piece(
                MediaKind.image,
                f'Gallery {index:04d}',
                index - start,
                assets.images[index % len(assets.images)].path,
                PieceOptions(
                    thumbnail=assets.images[index % len(assets.images)].thumbnail_path
                ),
            )
            for index in range(start, min(start + 100, photos))
        ]
        _save(root, GALLERY, start // 100 + 1, pieces)
    LibraryIndex(root).rebuild()


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
