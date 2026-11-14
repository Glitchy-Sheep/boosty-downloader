"""Raster recognition checks framing and dimensions without decompressing pixels."""

from pathlib import Path

import pytest
from support.raster_images import png_bytes

from boosty_downloader.infrastructure.raster_headers import (
    RasterHeader,
    inspect_raster_header,
)

FIXTURES = Path(__file__).parents[2] / 'fixtures' / 'thumbnails'
RASTER_FILES = [
    'baseline.jpg',
    'progressive.jpg',
    'small.gif',
    'lossy.webp',
    'lossless.webp',
    'extended.webp',
]


@pytest.mark.parametrize(
    'name',
    RASTER_FILES,
)
def test_genuine_raster_fixtures(name: str) -> None:
    assert inspect_raster_header((FIXTURES / name).read_bytes()) == RasterHeader(
        Path(name).suffix, 2, 3
    )


@pytest.mark.parametrize(('width', 'height'), [(1, 1), (480, 900), (481, 1), (2, 3)])
def test_png_dimensions(width: int, height: int) -> None:
    assert inspect_raster_header(png_bytes(width, height)) == RasterHeader(
        '.png', width, height
    )


@pytest.mark.parametrize(
    'data',
    [
        b'',
        b'<html>error</html>',
        b'<svg/>',
        b'GIF89a',
        b'\xff\xd8\xff\xd9',
        b'RIFFxxxxWEBP',
        png_bytes(0, 1),
        png_bytes(1, 0),
    ],
)
def test_unknown_or_zero_dimension_images(data: bytes) -> None:
    with pytest.raises(ValueError, match='raster'):
        inspect_raster_header(data)


@pytest.mark.parametrize(
    'name',
    RASTER_FILES,
)
def test_every_truncated_prefix_is_rejected(name: str) -> None:
    data = (FIXTURES / name).read_bytes()
    for length in range(len(data)):
        with pytest.raises(ValueError, match='raster'):
            inspect_raster_header(data[:length])


def test_every_truncated_png_prefix_is_rejected() -> None:
    data = png_bytes()
    for length in range(len(data)):
        with pytest.raises(ValueError, match='raster'):
            inspect_raster_header(data[:length])


def test_bad_png_checksum_is_rejected() -> None:
    data = bytearray(png_bytes())
    data[20] ^= 1
    with pytest.raises(ValueError, match='raster'):
        inspect_raster_header(bytes(data))


def test_extended_webp_canvas_must_match_encoded_frame() -> None:
    data = bytearray((FIXTURES / 'extended.webp').read_bytes())
    data[24] = 9
    with pytest.raises(ValueError, match='raster'):
        inspect_raster_header(bytes(data))


@pytest.mark.parametrize(
    ('name', 'offset'), [('baseline.jpg', 165), ('small.gif', 6), ('lossy.webp', 26)]
)
def test_zero_frame_width_is_rejected(name: str, offset: int) -> None:
    data = bytearray((FIXTURES / name).read_bytes())
    data[offset : offset + 2] = b'\0\0'
    with pytest.raises(ValueError, match='raster'):
        inspect_raster_header(bytes(data))
