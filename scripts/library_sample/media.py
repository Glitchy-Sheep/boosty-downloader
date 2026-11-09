"""Media histories, immutable asset placements and realistic recorded sizes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from random import Random
from typing import TypeAlias

from boosty_downloader.domain.stored_post import (
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
)
from library_sample.asset_models import (
    AssetCatalog,
    AttachmentAsset,
    AttachmentType,
    AudioAsset,
    ImageAsset,
    VideoAsset,
)
from library_sample.models import AssetPlacement, AuthorName, Scenario

_REMOVAL_PROBABILITY = 0.18

Asset: TypeAlias = ImageAsset | VideoAsset | AudioAsset | AttachmentAsset


@dataclass(frozen=True, slots=True)
class MediaInventory:
    """Recorded pieces and the files that are actually present on disk."""

    entries: dict[str, MediaEntry]
    files: tuple[AssetPlacement, ...]


@dataclass(frozen=True, slots=True)
class PieceSpec:
    """One deterministic scenario's media state."""

    kind: MediaKind
    status: MediaStatus = MediaStatus.downloaded
    removed: bool = False
    attachment: AttachmentAsset | None = None


@dataclass(frozen=True, slots=True)
class StoredPiece:
    """One media identity with its record and present files."""

    media_id: str
    entry: MediaEntry
    files: tuple[AssetPlacement, ...]


def build_media(
    post: PostMetadata, ordinal: int, assets: AssetCatalog
) -> MediaInventory:
    """Create inventory in stable order, keeping removal independent of local state."""
    pieces = [
        _piece(post, ordinal, position, spec, assets)
        for position, spec in enumerate(_specs(post, ordinal, assets))
    ]
    return MediaInventory(
        {piece.media_id: piece.entry for piece in pieces},
        tuple(placement for piece in pieces for placement in piece.files),
    )


def _specs(post: PostMetadata, ordinal: int, assets: AssetCatalog) -> list[PieceSpec]:
    match ordinal:
        case Scenario.all_kinds:
            return [PieceSpec(kind) for kind in MediaKind]
        case Scenario.text_only:
            return []
        case Scenario.attachments:
            return [
                PieceSpec(MediaKind.file, attachment=asset)
                for asset in assets.attachments
            ]
        case Scenario.local_states:
            return _state_examples()
        case Scenario.updated_since_seen:
            return [
                PieceSpec(kind)
                for kind in (
                    MediaKind.boosty_video,
                    MediaKind.audio,
                    MediaKind.external_video,
                )
            ]
        case _:
            return _themed_specs(post.author, assets) + _removed_history(post)


def _state_examples() -> list[PieceSpec]:
    current = [
        PieceSpec(kind, status)
        for kind, status in zip(MediaKind, MediaStatus, strict=True)
    ]
    removed = [PieceSpec(MediaKind.image, removed=True) for _ in range(6)]
    removed.extend(
        [
            PieceSpec(MediaKind.file, MediaStatus.pending, removed=True),
            PieceSpec(MediaKind.audio, MediaStatus.deleted, removed=True),
        ]
    )
    return current + removed


def _themed_specs(author: str, assets: AssetCatalog) -> list[PieceSpec]:
    match author:
        case AuthorName.music:
            archive = next(
                asset
                for asset in assets.attachments
                if asset.file_type == AttachmentType.archive
            )
            return [
                PieceSpec(MediaKind.audio),
                PieceSpec(MediaKind.file, attachment=archive),
                PieceSpec(MediaKind.image),
            ]
        case AuthorName.art:
            return [
                *[PieceSpec(MediaKind.image) for _ in range(8)],
                PieceSpec(MediaKind.boosty_video),
            ]
        case _:
            return [
                PieceSpec(MediaKind.image),
                PieceSpec(MediaKind.boosty_video),
                PieceSpec(MediaKind.file),
            ]


def _asset(spec: PieceSpec, position: int, assets: AssetCatalog) -> Asset:
    match spec.kind:
        case MediaKind.image:
            return assets.images[position % len(assets.images)]
        case MediaKind.audio:
            return assets.audio[position % len(assets.audio)]
        case MediaKind.boosty_video | MediaKind.external_video:
            return assets.videos[position % len(assets.videos)]
        case MediaKind.file:
            return (
                spec.attachment
                or assets.attachments[position % len(assets.attachments)]
            )


def _identity(post: PostMetadata, position: int, kind: MediaKind) -> str:
    if kind == MediaKind.external_video:
        return f'external_video:https://example.org/videos/{post.id}/{position}'
    return f'{kind.value}:{post.id}-{position}'


def _piece(
    post: PostMetadata,
    ordinal: int,
    position: int,
    spec: PieceSpec,
    assets: AssetCatalog,
) -> StoredPiece:
    asset = _asset(spec, position, assets)
    identity = _identity(post, position, spec.kind)
    path = f'media/{position:02d}-{asset.path.name}'
    entry = MediaEntry(
        kind=spec.kind,
        status=spec.status,
        position=position,
        added_at=post.created_at
        + timedelta(days=3 if ordinal == Scenario.updated_since_seen else 0, hours=1),
        removed_at=post.created_at + timedelta(days=4) if spec.removed else None,
        path=path,
        size=_claimed_size(post, identity, asset),
        title=asset.path.stem,
        error='Synthetic interrupted transfer'
        if spec.status == MediaStatus.failed
        else None,
    )
    files = (
        [AssetPlacement(path, asset.path)]
        if spec.status == MediaStatus.downloaded
        else []
    )
    _describe_asset(entry, asset, post)
    if isinstance(asset, VideoAsset):
        entry.preview_path = f'previews/{position:02d}.png'
        files.append(AssetPlacement(entry.preview_path, asset.preview.path))
    return StoredPiece(identity, entry, tuple(files))


def _describe_asset(entry: MediaEntry, asset: Asset, post: PostMetadata) -> None:
    if isinstance(asset, AttachmentAsset):
        entry.filename = asset.path.name
    if isinstance(asset, (ImageAsset, VideoAsset)):
        entry.width, entry.height = asset.width, asset.height
    if isinstance(asset, (AudioAsset, VideoAsset)):
        entry.duration = asset.duration
    if isinstance(asset, AudioAsset):
        entry.artist = post.author


def _claimed_size(post: PostMetadata, identity: str, asset: Asset) -> int:
    draw = Random(f'{identity}:size')  # noqa: S311 - reproducible sample
    if isinstance(asset, AudioAsset):
        return round(asset.duration.total_seconds() * draw.uniform(256, 320) * 1000 / 8)
    if isinstance(asset, ImageAsset):
        minimum, maximum = (1.5, 14.0) if post.author == AuthorName.art else (0.2, 3.5)
    elif isinstance(asset, VideoAsset):
        minimum, maximum = (
            (65.0, 95.0) if post.author == AuthorName.art else (150.0, 2400.0)
        )
    else:
        limits = _ATTACHMENT_RANGES.get(asset.file_type, SizeRange(0.0003, 0.008))
        minimum, maximum = limits.minimum, limits.maximum
    return round(draw.uniform(minimum, maximum) * 1_000_000)


@dataclass(frozen=True, slots=True)
class SizeRange:
    """Lower and upper recorded megabytes for one attachment category."""

    minimum: float
    maximum: float


_ATTACHMENT_RANGES = {
    AttachmentType.archive: SizeRange(90.0, 1800.0),
    AttachmentType.video: SizeRange(120.0, 1500.0),
    AttachmentType.image: SizeRange(3.0, 14.0),
    AttachmentType.audio: SizeRange(8.0, 24.0),
    AttachmentType.program: SizeRange(18.0, 320.0),
    AttachmentType.model: SizeRange(4.0, 60.0),
    AttachmentType.pdf: SizeRange(0.4, 18.0),
    AttachmentType.slides: SizeRange(0.4, 18.0),
    AttachmentType.book: SizeRange(0.3, 4.0),
    AttachmentType.font: SizeRange(0.05, 1.0),
    AttachmentType.document: SizeRange(0.015, 0.08),
    AttachmentType.sheet: SizeRange(0.015, 0.08),
}


def _removed_history(post: PostMetadata) -> list[PieceSpec]:
    """Stable post-local history keeps most removed copies and two missing subsets."""
    draw = Random(f'{post.id}:removal')  # noqa: S311 - reproducible sample
    if draw.random() >= _REMOVAL_PROBABILITY:
        return []
    status = draw.choices(
        [MediaStatus.downloaded, MediaStatus.pending, MediaStatus.deleted],
        weights=[7, 2, 1],
    )[0]
    return [PieceSpec(draw.choice(list(MediaKind)), status, removed=True)]
