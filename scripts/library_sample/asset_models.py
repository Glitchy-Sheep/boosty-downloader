"""Typed media assets shared by the sample's content and file generators."""

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from pathlib import Path


class AssetBackend(str, Enum):
    """Requested media generator; catalogs contain a resolved backend."""

    auto = 'auto'
    ffmpeg = 'ffmpeg'
    fallback = 'fallback'


class AttachmentType(str, Enum):
    """Sample coverage categories, independent of the production file classifier."""

    pdf = 'pdf'
    document = 'document'
    book = 'book'
    slides = 'slides'
    sheet = 'sheet'
    image = 'image'
    audio = 'audio'
    video = 'video'
    archive = 'archive'
    model = 'model'
    code = 'code'
    font = 'font'
    program = 'program'
    script = 'script'
    other = 'other'


@dataclass(frozen=True, slots=True)
class ImageAsset:
    """One raster image, its pixel dimensions and an optional small copy."""

    path: Path
    width: int
    height: int
    thumbnail_path: Path | None = None


@dataclass(frozen=True, slots=True)
class VideoAsset:
    """One playable clip and its preview frame."""

    path: Path
    duration: timedelta
    preview: ImageAsset
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class AudioAsset:
    """One playable track and its duration."""

    path: Path
    duration: timedelta


@dataclass(frozen=True, slots=True)
class AttachmentAsset:
    """A representative file for one attachment category."""

    path: Path
    file_type: AttachmentType


@dataclass(frozen=True, slots=True)
class AssetCatalog:
    """Stable ordered assets written once in the owned sample directory."""

    backend: AssetBackend
    images: tuple[ImageAsset, ...]
    avatars: tuple[ImageAsset, ...]
    covers: tuple[ImageAsset, ...]
    videos: tuple[VideoAsset, ...]
    audio: tuple[AudioAsset, ...]
    attachments: tuple[AttachmentAsset, ...]
