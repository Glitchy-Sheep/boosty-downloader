"""Deterministic textured PNG originals with matching sampled thumbnails."""

from __future__ import annotations

import struct
import zlib
from random import Random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from library_sample.asset_models import ImageAsset

THUMBNAIL_WIDTH = 480
_TEXTURE_LEVELS = 65


def write_photo_png(image: ImageAsset, top: str, bottom: str, seed: int) -> Path:
    """Keep real pixel detail in the original and sample that image at 480px wide."""
    draw = Random(seed)  # noqa: S311 - reproducible synthetic image texture
    first, last = bytes.fromhex(top), bytes.fromhex(bottom)
    rows = [
        _row(image.width, row / (image.height - 1), first, last, draw)
        for row in range(image.height)
    ]
    _write_png(image.path, image.width, image.height, rows)
    return _write_thumbnail(image, rows)


def _row(width: int, ratio: float, first: bytes, last: bytes, draw: Random) -> bytes:
    noise = draw.randbytes(width)
    row = bytearray(width * 3)
    for channel, (start, end) in enumerate(zip(first, last, strict=True)):
        base = round(start + (end - start) * ratio)
        palette = bytes(
            max(0, min(255, base + value % _TEXTURE_LEVELS - _TEXTURE_LEVELS // 2))
            for value in range(256)
        )
        row[channel::3] = noise.translate(palette)
    return bytes(row)


def _write_thumbnail(image: ImageAsset, rows: list[bytes]) -> Path:
    height = round(image.height * THUMBNAIL_WIDTH / image.width)
    columns = [
        column * image.width // THUMBNAIL_WIDTH for column in range(THUMBNAIL_WIDTH)
    ]
    small_rows = [
        b''.join(
            rows[row * image.height // height][column * 3 : column * 3 + 3]
            for column in columns
        )
        for row in range(height)
    ]
    path = image.path.with_stem(f'{image.path.stem}_thumb')
    _write_png(path, THUMBNAIL_WIDTH, height, small_rows)
    return path


def _write_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    header = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    pixels = b''.join(b'\x00' + row for row in rows)
    path.write_bytes(
        b'\x89PNG\r\n\x1a\n'
        + _chunk(b'IHDR', header)
        + _chunk(b'IDAT', zlib.compress(pixels))
        + _chunk(b'IEND', b'')
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack('>I', len(data))
        + kind
        + data
        + struct.pack('>I', zlib.crc32(kind + data))
    )
