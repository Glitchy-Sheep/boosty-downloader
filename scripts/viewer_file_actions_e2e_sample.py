"""Canonical file-action corpus with portable names and immutable source assets."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from library_sample.asset_models import AssetBackend, AssetCatalog
from library_sample.assets import create_assets
from viewer_media_e2e_sample import Piece

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
from boosty_downloader.infrastructure.library.post_store import JsonPostStore

AUTHOR = 'file_action_checks'
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
MANIFEST = '.boosty-downloader/file-action-sources.json'
Fragment = PostDataChunkText.TextFragment


def post_id(number: int) -> str:
    """Return the stable post identities used by browser assertions."""
    return f'50000000-0000-4000-8000-{number:012d}'


def _metadata(number: int) -> PostMetadata:
    created = NOW - timedelta(days=number)
    return PostMetadata(
        post_id(number),
        AUTHOR,
        f'https://boosty.to/{AUTHOR}/posts/{post_id(number)}',
        f'File action post {number}',
        created,
        created,
    )


def _piece(kind: MediaKind, name: str, source: Path, position: int) -> Piece:
    return Piece(
        f'{kind.value}:{position}',
        MediaEntry(
            kind,
            MediaStatus.downloaded,
            NOW,
            position,
            path=f'media/{name}',
            size=source.stat().st_size,
            title=f'Display title {position}',
            filename=f'Original server filename {position}.other',
        ),
        source,
    )


def _extra_files(directory: Path) -> list[Path]:
    examples = {
        'Attachment.html': '<script>fetch("/file-attachment-executed");window.__fileAttack=1</script>',
        'Launcher with a deliberately long name that must preserve its final suffix.settingcontent-ms': 'Inert fixture launcher; never execute.\n',
        'invoice.pdf.exe': 'Inert fixture program; never execute.\n',
        'Заметки  с пробелами, 100%25.txt': 'Exact spaces, comma and literal percent.\n',
    }
    for name, content in examples.items():
        (directory / name).write_text(content, encoding='utf-8')
    return [directory / name for name in examples]


def _pieces(assets: AssetCatalog, directory: Path) -> list[Piece]:
    files = [asset.path for asset in assets.attachments]
    files.extend(_extra_files(directory))
    pieces = [
        _piece(MediaKind.file, source.name, source, position)
        for position, source in enumerate(files)
    ]
    for kind, asset in (
        (MediaKind.image, assets.images[0]),
        (MediaKind.boosty_video, assets.videos[0]),
        (MediaKind.audio, assets.audio[0]),
    ):
        piece = _piece(
            kind, f'Playable {kind.value}{asset.path.suffix}', asset.path, len(pieces)
        )
        if kind is not MediaKind.image:
            piece.entry.duration = timedelta(seconds=24)
        pieces.append(piece)
    return pieces


def _retained(pieces: list[Piece]) -> list[Piece]:
    retained: list[Piece] = []
    for original in (pieces[0], *pieces[-3:]):
        if original.source is None:
            message = 'Retained fixtures require an immutable source.'
            raise ValueError(message)
        piece = _piece(
            original.entry.kind,
            f'Retained {original.source.name}',
            original.source,
            len(pieces) + len(retained),
        )
        piece.entry.removed_at = NOW + timedelta(days=1)
        piece.entry.duration = original.entry.duration
        retained.append(piece)
    return retained


def _blocks(pieces: list[Piece]) -> list[Block]:
    return [
        TextBlock([Fragment('Attachment needle in authored text.')]),
        ParagraphBreak(),
        TextBlock(
            [
                Fragment(
                    'Another file post',
                    f'https://boosty.to/{AUTHOR}/posts/{post_id(2)}',
                )
            ]
        ),
        ParagraphBreak(),
        *[MediaBlock(piece.key) for piece in pieces if not piece.entry.removed_at],
    ]


def _save(root: Path, number: int, pieces: list[Piece]) -> dict[str, str]:
    store = JsonPostStore(root)
    metadata = _metadata(number)
    folder = store.choose_post_folder(metadata)
    sources: dict[str, str] = {}
    for piece in pieces:
        if piece.source is None or piece.entry.path is None:
            message = 'File-action fixtures require a source and stored path.'
            raise ValueError(message)
        destination = root / folder / piece.entry.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.link(piece.source, destination)
        sources[destination.relative_to(root).as_posix()] = piece.source.relative_to(
            root
        ).as_posix()
    store.save_post(
        folder,
        StoredPost(
            metadata,
            PostSync(NOW, NOW),
            _blocks(pieces),
            {piece.key: piece.entry for piece in pieces},
        ),
    )
    return sources


def prepare(root: Path) -> None:
    """Build only a fresh corpus, retaining the original bytes for comparisons."""
    root.mkdir()
    initialize_library(root)
    directory = root / '.boosty-downloader' / 'file-action-assets'
    assets = create_assets(directory, seed=59, backend=AssetBackend.fallback)
    store = JsonPostStore(root)
    store.save_author(AuthorInfo(AUTHOR, NOW, title='File Action Checks'))
    pieces = _pieces(assets, directory)
    sources = _save(root, 1, [*pieces, *_retained(pieces)])
    sources.update(_save(root, 2, [pieces[0]]))
    store.save_locked_post(LockedPost(_metadata(3), NOW))
    (root / MANIFEST).write_text(
        json.dumps(sources, ensure_ascii=False), encoding='utf-8'
    )
    LibraryIndex(root).rebuild()


if __name__ == '__main__':
    prepare(Path(sys.argv[1]))
