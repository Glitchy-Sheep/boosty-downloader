"""Inspect raster dimensions and framing without decoding compressed pixels."""

# ruff: noqa: PLR2004 - Raster specifications define byte offsets and marker values.

from dataclasses import dataclass
from struct import unpack
from typing import Final, NoReturn
from zlib import crc32

PNG_SIGNATURE: Final = b'\x89PNG\r\n\x1a\n'
_JPEG_FRAMES: Final = frozenset({0xC0, 0xC1, 0xC2})
_PNG_DEPTHS: Final = {
    0: {1, 2, 4, 8, 16},
    2: {8, 16},
    3: {1, 2, 4, 8},
    4: {8, 16},
    6: {8, 16},
}


@dataclass(frozen=True, slots=True)
class RasterHeader:
    """A recognized format and its declared canvas dimensions, in pixels."""

    extension: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RasterDimensions:
    """Declared raster width and height, in pixels."""

    width: int
    height: int


@dataclass(frozen=True, slots=True)
class JpegSegment:
    """A JPEG marker, its payload, and the next byte offset."""

    marker: int
    payload: bytes
    next_offset: int


@dataclass(frozen=True, slots=True)
class WebpChunk:
    """A WebP chunk identifier and its payload."""

    kind: bytes
    payload: bytes


def inspect_raster_header(data: bytes) -> RasterHeader:
    """Reject unknown/truncated framing; compressed pixel validity is not checked."""
    if data.startswith(PNG_SIGNATURE):
        dimensions = _png_dimensions(data)
        extension = '.png'
    elif data.startswith(b'\xff\xd8'):
        dimensions = _jpeg_dimensions(data)
        extension = '.jpg'
    elif data[:6] in {b'GIF87a', b'GIF89a'}:
        dimensions = _gif_dimensions(data)
        extension = '.gif'
    elif data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        dimensions = _webp_dimensions(data)
        extension = '.webp'
    else:
        _invalid_raster()
    _require(dimensions.width > 0 and dimensions.height > 0)
    return RasterHeader(extension, dimensions.width, dimensions.height)


def _require(condition: bool) -> None:  # noqa: FBT001 - Internal parser assertion.
    if not condition:
        _invalid_raster()


def _invalid_raster() -> NoReturn:
    message = 'Unrecognized or malformed raster image header'
    raise ValueError(message)


def _png_dimensions(data: bytes) -> RasterDimensions:
    _require(len(data) >= 33 and data[8:16] == b'\0\0\0\rIHDR')
    width, height, depth, color, compression, filtering, interlace = unpack(
        '>IIBBBBB', data[16:29]
    )
    _require(width <= 0x7FFFFFFF and height <= 0x7FFFFFFF)
    _require(depth in _PNG_DEPTHS.get(color, set()))
    _require(compression == filtering == 0 and interlace in {0, 1})
    _check_png_chunks(data)
    return RasterDimensions(width=width, height=height)


def _check_png_chunks(data: bytes) -> None:
    offset, has_pixels = 8, False
    while offset < len(data):
        _require(offset + 12 <= len(data))
        size = int.from_bytes(data[offset : offset + 4], 'big')
        end = offset + 12 + size
        _require(end <= len(data))
        kind = data[offset + 4 : offset + 8]
        _require(kind != b'IHDR' or offset == 8)
        _require(
            crc32(data[offset + 4 : end - 4])
            == int.from_bytes(data[end - 4 : end], 'big')
        )
        has_pixels |= kind == b'IDAT' and size > 0
        if kind == b'IEND':
            _require(size == 0 and end == len(data) and has_pixels)
            return
        offset = end
    _invalid_raster()


def _jpeg_dimensions(data: bytes) -> RasterDimensions:
    _require(data.endswith(b'\xff\xd9'))
    offset, dimensions = 2, None
    while offset < len(data) - 2:
        segment = _jpeg_segment(data, offset)
        if segment.marker in _JPEG_FRAMES:
            dimensions = _jpeg_frame(segment.payload)
        if segment.marker == 0xDA:
            _require(
                dimensions is not None
                and len(segment.payload) >= 6
                and segment.next_offset < len(data) - 2
            )
            if dimensions is not None:
                return dimensions
        offset = segment.next_offset
    _invalid_raster()


def _jpeg_segment(data: bytes, offset: int) -> JpegSegment:
    _require(data[offset] == 0xFF)
    while offset < len(data) and data[offset] == 0xFF:
        offset += 1
    _require(offset + 3 <= len(data))
    marker = data[offset]
    _require(marker not in {0x00, 0xD8, 0xD9, *range(0xD0, 0xD8)})
    size = int.from_bytes(data[offset + 1 : offset + 3], 'big')
    end = offset + 1 + size
    _require(size >= 2 and end <= len(data) - 2)
    return JpegSegment(marker=marker, payload=data[offset + 3 : end], next_offset=end)


def _jpeg_frame(segment: bytes) -> RasterDimensions:
    _require(len(segment) >= 6)
    _require(segment[5] > 0)
    _require(segment[0] in {8, 12} and len(segment) == 6 + 3 * segment[5])
    height, width = unpack('>HH', segment[1:5])
    return RasterDimensions(width=width, height=height)


def _gif_dimensions(data: bytes) -> RasterDimensions:
    _require(len(data) >= 14)
    width, height = unpack('<HH', data[6:10])
    offset, has_pixels = 13 + _gif_palette_size(data[10]), False
    while offset < len(data):
        kind = data[offset]
        if kind == 0x3B:
            _require(offset == len(data) - 1 and has_pixels)
            return RasterDimensions(width=width, height=height)
        if kind == 0x21:
            offset = _gif_subblocks_end(data, offset + 2)
        elif kind == 0x2C:
            offset = _gif_frame_end(data, offset + 1, width, height)
            has_pixels = True
        else:
            _invalid_raster()
    _invalid_raster()


def _gif_palette_size(packed: int) -> int:
    return 3 * (2 ** ((packed & 7) + 1)) if packed & 0x80 else 0


def _gif_subblocks_end(data: bytes, offset: int) -> int:
    while offset < len(data):
        size = data[offset]
        offset += 1 + size
        _require(offset <= len(data))
        if size == 0:
            return offset
    _invalid_raster()


def _gif_frame_end(data: bytes, offset: int, width: int, height: int) -> int:
    _require(offset + 9 <= len(data))
    left, top, frame_width, frame_height = unpack('<HHHH', data[offset : offset + 8])
    _require(frame_width > 0 and frame_height > 0)
    _require(left + frame_width <= width and top + frame_height <= height)
    offset += 9 + _gif_palette_size(data[offset + 8])
    _require(offset + 1 < len(data) and 2 <= data[offset] <= 8)
    _require(data[offset + 1] > 0)
    return _gif_subblocks_end(data, offset + 1)


def _webp_dimensions(data: bytes) -> RasterDimensions:
    _require(len(data) >= 20 and int.from_bytes(data[4:8], 'little') + 8 == len(data))
    chunks = _webp_chunks(data[12:])
    header = chunks[0]
    if header.kind != b'VP8X':
        _require(len(chunks) == 1)
        return _webp_frame_dimensions(header)
    _require(len(header.payload) == 10)
    dimensions = RasterDimensions(
        width=int.from_bytes(header.payload[4:7], 'little') + 1,
        height=int.from_bytes(header.payload[7:10], 'little') + 1,
    )
    frames = [chunk for chunk in chunks if chunk.kind in {b'VP8 ', b'VP8L'}]
    _require(len(frames) == 1 and not any(chunk.kind == b'ANIM' for chunk in chunks))
    _require(_webp_frame_dimensions(frames[0]) == dimensions)
    return dimensions


def _webp_chunks(data: bytes) -> list[WebpChunk]:
    chunks: list[WebpChunk] = []
    offset = 0
    while offset < len(data):
        _require(offset + 8 <= len(data))
        size = int.from_bytes(data[offset + 4 : offset + 8], 'little')
        end = offset + 8 + size
        _require(end + size % 2 <= len(data))
        chunks.append(
            WebpChunk(kind=data[offset : offset + 4], payload=data[offset + 8 : end])
        )
        offset = end + size % 2
    _require(bool(chunks))
    return chunks


def _webp_frame_dimensions(chunk: WebpChunk) -> RasterDimensions:
    payload = chunk.payload
    if chunk.kind == b'VP8 ':
        _require(len(payload) > 10 and payload[3:6] == b'\x9d\x01\x2a')
        _require(payload[0] & 1 == 0)
        width, height = unpack('<HH', payload[6:10])
        return RasterDimensions(width=width & 0x3FFF, height=height & 0x3FFF)
    _require(chunk.kind == b'VP8L' and len(payload) > 5 and payload[0] == 0x2F)
    bits = int.from_bytes(payload[1:5], 'little')
    _require(bits >> 29 == 0)
    return RasterDimensions(
        width=(bits & 0x3FFF) + 1, height=((bits >> 14) & 0x3FFF) + 1
    )
