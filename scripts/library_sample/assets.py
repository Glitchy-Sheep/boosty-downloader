"""Deterministic playable media for an isolated synthetic library."""

from __future__ import annotations

import shutil
import struct
import subprocess
import wave
import zlib
from dataclasses import dataclass, replace
from datetime import timedelta
from hashlib import sha256
from pathlib import Path
from typing import Final

from library_sample.asset_models import (
    AssetBackend,
    AssetCatalog,
    AudioAsset,
    ImageAsset,
    VideoAsset,
)
from library_sample.attachments import create_attachments
from library_sample.photo_png import write_photo_png


@dataclass(frozen=True, slots=True)
class _Dimensions:
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class _Palette:
    first: str
    second: str
    third: str


_PALETTES: Final = (
    _Palette('ff7e5f', 'feb47b', '6a3093'),
    _Palette('2b5876', '4e4376', '00c9ff'),
    _Palette('11998e', '38ef7d', '0b3d2e'),
    _Palette('fc466b', '3f5efb', '1b1b3a'),
    _Palette('f7971e', 'ffd200', '7a2e0e'),
    _Palette('654ea3', 'eaafc8', '1f1c2c'),
    _Palette('1a2980', '26d0ce', '0f0c29'),
    _Palette('c94b4b', '4b134f', 'f8b195'),
    _Palette('134e5e', '71b280', '0b1f24'),
    _Palette('e96443', '904e95', '2c2c54'),
    _Palette('3c3b3f', '605c3c', 'd1c8a4'),
    _Palette('00416a', 'e4e5e6', '1c1c1c'),
)
_IMAGE_SHAPES: Final = (
    _Dimensions(2400, 1350),
    _Dimensions(1600, 2400),
    _Dimensions(2000, 2000),
)
_VIDEO_SIZE: Final = _Dimensions(640, 360)
_VIDEO_SECONDS: Final = (24, 75, 150)
_AUDIO_SECONDS: Final = (45, 150, 420)
_FALLBACK_DIR: Final = Path(__file__).parent / 'fallback_assets'
_MAX_SEED: Final = 2**32 - 1
_SAMPLE_RATE: Final = 8000


def create_assets(
    directory: Path, *, seed: int, backend: AssetBackend = AssetBackend.auto
) -> AssetCatalog:
    """Populate a new asset directory; reject failed encoders and existing outputs."""
    _validate_seed(seed)
    resolved = _resolve_backend(backend)
    directory.mkdir()
    images = _create_images(directory, seed, resolved)
    avatars = _create_author_images(directory, seed, resolved, cover=False)
    covers = _create_author_images(directory, seed, resolved, cover=True)
    videos = _create_videos(directory, seed, resolved)
    audio = _create_audio(directory, seed, resolved)
    attachments = create_attachments(
        directory, images=images, videos=videos, audio=audio
    )
    return AssetCatalog(resolved, images, avatars, covers, videos, audio, attachments)


def _validate_seed(seed: object) -> None:
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= _MAX_SEED
    ):
        message = 'Asset seed must be an unsigned 32-bit integer'
        raise ValueError(message)


def _resolve_backend(backend: AssetBackend) -> AssetBackend:
    if backend is AssetBackend.fallback:
        return backend
    if shutil.which('ffmpeg') is not None:
        return AssetBackend.ffmpeg
    if backend is AssetBackend.ffmpeg:
        message = 'ffmpeg was requested but is not installed'
        raise RuntimeError(message)
    return AssetBackend.fallback


def _asset_seed(seed: int, name: str) -> int:
    digest = sha256(f'{seed}/{name}'.encode()).digest()
    return int.from_bytes(digest[:4], 'big') % (2**31)


def _run_ffmpeg(*args: str) -> None:
    subprocess.run(
        ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-n', *args],
        check=True,
        capture_output=True,
        timeout=300,
    )


def _create_images(
    directory: Path, seed: int, backend: AssetBackend
) -> tuple[ImageAsset, ...]:
    return tuple(
        _create_photo(
            directory / f'image_{number:02d}',
            size=_IMAGE_SHAPES[number % len(_IMAGE_SHAPES)],
            palette=_PALETTES[number % len(_PALETTES)],
            seed=_asset_seed(seed, f'image/{number}'),
            backend=backend,
        )
        for number in range(18)
    )


def _create_photo(
    stem: Path,
    *,
    size: _Dimensions,
    palette: _Palette,
    seed: int,
    backend: AssetBackend,
) -> ImageAsset:
    if backend is AssetBackend.fallback:
        image = ImageAsset(stem.with_suffix('.png'), size.width, size.height)
        thumbnail = write_photo_png(image, palette.first, palette.third, seed)
        return replace(image, thumbnail_path=thumbnail)
    path = stem.with_suffix('.jpg')
    source = _gradient(size, palette, seed, moving=False)
    source += f',noise=alls=65:all_seed={seed}'
    _run_ffmpeg('-f', 'lavfi', '-i', source, '-frames:v', '1', '-q:v', '1', str(path))
    thumbnail = stem.with_name(f'{stem.name}_thumb').with_suffix('.jpg')
    _run_ffmpeg(
        '-i',
        str(path),
        '-vf',
        'scale=480:-2',
        '-frames:v',
        '1',
        '-q:v',
        '4',
        str(thumbnail),
    )
    return ImageAsset(path, size.width, size.height, thumbnail)


def _create_author_images(
    directory: Path, seed: int, backend: AssetBackend, *, cover: bool
) -> tuple[ImageAsset, ...]:
    name = 'cover' if cover else 'avatar'
    size = _Dimensions(1500, 400) if cover else _Dimensions(256, 256)
    return tuple(
        _create_image(
            directory / f'{name}_{number}',
            size=size,
            palette=_PALETTES[(number * 3 + int(cover)) % len(_PALETTES)],
            seed=_asset_seed(seed, f'{name}/{number}'),
            backend=backend,
        )
        for number in range(3)
    )


def _create_image(
    stem: Path,
    *,
    size: _Dimensions,
    palette: _Palette,
    seed: int,
    backend: AssetBackend,
) -> ImageAsset:
    if backend is AssetBackend.fallback:
        path = stem.with_suffix('.png')
        _write_png(path, size, palette.first)
    else:
        path = stem.with_suffix('.jpg')
        source = _gradient(size, palette, seed, moving=False)
        _run_ffmpeg(
            '-f', 'lavfi', '-i', source, '-frames:v', '1', '-q:v', '3', str(path)
        )
    return ImageAsset(path, size.width, size.height)


def _gradient(size: _Dimensions, palette: _Palette, seed: int, *, moving: bool) -> str:
    speed = '0.03' if moving else '0'
    return (
        f'gradients=s={size.width}x{size.height}:c0=0x{palette.first}'
        f':c1=0x{palette.second}:c2=0x{palette.third}:n=3:seed={seed}:speed={speed},'
        f'gblur=sigma=30,format=yuv420p,noise=c0s=3:all_seed={seed},vignette=PI/6'
    )


def _write_png(path: Path, size: _Dimensions, color: str) -> None:
    rgb = bytes.fromhex(color)
    rows = (b'\x00' + rgb * size.width) * size.height
    header = struct.pack('>IIBBBBB', size.width, size.height, 8, 2, 0, 0, 0)
    path.write_bytes(
        b'\x89PNG\r\n\x1a\n'
        + _png_chunk(b'IHDR', header)
        + _png_chunk(b'IDAT', zlib.compress(rows))
        + _png_chunk(b'IEND', b'')
    )


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack('>I', len(data))
        + kind
        + data
        + struct.pack('>I', zlib.crc32(kind + data))
    )


def _create_videos(
    directory: Path, seed: int, backend: AssetBackend
) -> tuple[VideoAsset, ...]:
    return tuple(
        _create_video(directory, seconds, seed, backend) for seconds in _VIDEO_SECONDS
    )


def _create_video(
    directory: Path, seconds: int, seed: int, backend: AssetBackend
) -> VideoAsset:
    path = directory / f'video_{seconds}s.mp4'
    palette = _PALETTES[6 + _VIDEO_SECONDS.index(seconds) * 2]
    if backend is AssetBackend.fallback:
        shutil.copyfile(_FALLBACK_DIR / path.name, path)
    else:
        _encode_video(path, seconds, palette, _asset_seed(seed, path.name))
    preview = _create_image(
        directory / f'video_{seconds}s_preview',
        size=_VIDEO_SIZE,
        palette=palette,
        seed=_asset_seed(seed, path.name),
        backend=backend,
    )
    return VideoAsset(
        path, timedelta(seconds=seconds), preview, _VIDEO_SIZE.width, _VIDEO_SIZE.height
    )


def _encode_video(path: Path, seconds: int, palette: _Palette, seed: int) -> None:
    source = _gradient(_VIDEO_SIZE, palette, seed, moving=True)
    _run_ffmpeg(
        '-f',
        'lavfi',
        '-i',
        source,
        '-f',
        'lavfi',
        '-i',
        'color=c=white@0.75:s=640x6:r=25',
        '-filter_complex',
        f"[0][1]overlay=x='-W+W*t/{seconds}':y=H-h:eval=frame,format=yuv420p",
        '-t',
        str(seconds),
        '-c:v',
        'libx264',
        '-crf',
        '32',
        '-preset',
        'veryfast',
        '-movflags',
        '+faststart',
        '-threads',
        '1',
        str(path),
    )


def _create_audio(
    directory: Path, seed: int, backend: AssetBackend
) -> tuple[AudioAsset, ...]:
    return tuple(
        _create_track(directory, seconds, seed, backend) for seconds in _AUDIO_SECONDS
    )


def _create_track(
    directory: Path, seconds: int, seed: int, backend: AssetBackend
) -> AudioAsset:
    if backend is AssetBackend.fallback:
        path = directory / f'audio_{seconds}s.wav'
        _write_wave(path, seconds)
    else:
        path = directory / f'audio_{seconds}s.m4a'
        source = f'anoisesrc=color=pink:amplitude=0.12:duration={seconds}:seed={_asset_seed(seed, path.name)}'
        _run_ffmpeg(
            '-f',
            'lavfi',
            '-i',
            source,
            '-af',
            'lowpass=f=900,afade=t=in:d=2',
            '-c:a',
            'aac',
            '-b:a',
            '64k',
            str(path),
        )
    return AudioAsset(path, timedelta(seconds=seconds))


def _write_wave(path: Path, seconds: int) -> None:
    # A quiet repeated triangle wave keeps fallback playback small and deterministic.
    period = b''.join(struct.pack('<h', (min(n, 40 - n) - 10) * 40) for n in range(40))
    second = period * (_SAMPLE_RATE // 40)
    with wave.open(str(path), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(_SAMPLE_RATE)
        for _ in range(seconds):
            output.writeframesraw(second)
