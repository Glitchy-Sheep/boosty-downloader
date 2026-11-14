"""Small genuine raster fixtures for thumbnail transfer and header checks."""

from struct import pack
from zlib import compress, crc32


def png_bytes(width: int = 2, height: int = 3) -> bytes:
    header = pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)
    rows = (b'\0' + b'\xff\0\0' * width) * height
    return (
        b'\x89PNG\r\n\x1a\n'
        + png_chunk(b'IHDR', header)
        + png_chunk(b'IDAT', compress(rows))
        + png_chunk(b'IEND', b'')
    )


def png_chunk(kind: bytes, data: bytes) -> bytes:
    return pack('>I', len(data)) + kind + data + pack('>I', crc32(kind + data))
