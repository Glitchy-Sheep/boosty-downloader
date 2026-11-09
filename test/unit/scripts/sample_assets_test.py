from __future__ import annotations

import json
import os
import struct
import subprocess
import wave
import zlib
from typing import TYPE_CHECKING, cast
from unittest.mock import Mock
from xml.etree import ElementTree as ET
from zipfile import ZIP_STORED, ZipFile

import pytest
from library_sample import assets
from library_sample.asset_models import AssetBackend, AssetCatalog, AttachmentType
from library_sample.assets import create_assets

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(scope='module')
def fallback_catalog(tmp_path_factory: pytest.TempPathFactory) -> AssetCatalog:
    return create_assets(
        tmp_path_factory.mktemp('assets') / 'catalog',
        seed=7,
        backend=AssetBackend.fallback,
    )


def test_fallback_catalog_has_real_dimensions_and_duration_variants(
    fallback_catalog: AssetCatalog,
):
    catalog = fallback_catalog
    assert catalog.backend is AssetBackend.fallback
    assert len(catalog.images) == 18
    assert len(catalog.avatars) == len(catalog.covers) == 3
    assert {(image.width, image.height) for image in catalog.images} == {
        (960, 540),
        (640, 960),
        (800, 800),
    }
    for image in (
        *catalog.images,
        *catalog.avatars,
        *catalog.covers,
        *(clip.preview for clip in catalog.videos),
    ):
        chunks = dict(_png_chunks(image.path))
        width, height, bits, color, *_ = struct.unpack('>IIBBBBB', chunks[b'IHDR'])
        assert (width, height, bits, color) == (image.width, image.height, 8, 2)
        assert len(zlib.decompress(chunks[b'IDAT'])) == height * (1 + width * 3)
    assert [clip.duration.total_seconds() for clip in catalog.videos] == [24, 75, 150]
    assert [track.duration.total_seconds() for track in catalog.audio] == [45, 150, 420]
    for track in catalog.audio:
        with wave.open(str(track.path), 'rb') as audio:
            assert audio.getnchannels() == 1
            assert audio.getsampwidth() == 2
            assert (
                audio.getnframes() / audio.getframerate()
                == track.duration.total_seconds()
            )
            assert any(audio.readframes(40))


def _png_chunks(path: Path) -> Iterator[tuple[bytes, bytes]]:
    raw = path.read_bytes()
    assert raw[:8] == b'\x89PNG\r\n\x1a\n'
    offset = 8
    while offset < len(raw):
        length = int.from_bytes(raw[offset : offset + 4], 'big')
        kind = raw[offset + 4 : offset + 8]
        data = raw[offset + 8 : offset + 8 + length]
        checksum = int.from_bytes(
            raw[offset + 8 + length : offset + 12 + length], 'big'
        )
        assert checksum == zlib.crc32(kind + data)
        yield kind, data
        offset += length + 12
    assert offset == len(raw)


def _mp4_boxes(raw: bytes) -> Iterator[tuple[bytes, bytes]]:
    offset = 0
    while offset < len(raw):
        length = int.from_bytes(raw[offset : offset + 4], 'big')
        assert length >= 8
        yield raw[offset + 4 : offset + 8], raw[offset + 8 : offset + length]
        offset += length
    assert offset == len(raw)


def test_fallback_mp4_has_seekable_container_and_matching_duration(
    fallback_catalog: AssetCatalog,
):
    for video in fallback_catalog.videos:
        boxes = dict(_mp4_boxes(video.path.read_bytes()))
        assert b'ftyp' in boxes
        assert boxes[b'mdat']
        movie = dict(_mp4_boxes(boxes[b'moov']))
        header = movie[b'mvhd']
        assert header[0] == 0
        timescale = int.from_bytes(header[12:16], 'big')
        duration = int.from_bytes(header[16:20], 'big')
        assert duration / timescale == video.duration.total_seconds()
        assert b'avc1' in movie[b'trak']
        assert b'stss' in movie[b'trak']


def test_every_attachment_category_has_valid_content(fallback_catalog: AssetCatalog):
    attachments = {item.file_type: item.path for item in fallback_catalog.attachments}
    assert list(attachments) == list(AttachmentType)
    assert all(path.is_file() and path.stat().st_size for path in attachments.values())
    pdf = attachments[AttachmentType.pdf]
    assert pdf.name == 'Заметки к уроку, часть 1.pdf'
    _check_pdf_offsets(pdf.read_bytes())
    for kind in (
        AttachmentType.document,
        AttachmentType.book,
        AttachmentType.slides,
        AttachmentType.archive,
    ):
        _check_archive(attachments[kind])
    assert json.loads(attachments[AttachmentType.code].read_text()) == {
        'accent': '#7c9cff'
    }
    assert attachments[AttachmentType.model].read_text().count('facet normal') == 4
    assert attachments[AttachmentType.sheet].read_text().splitlines()[1] == 'Free,0'
    assert (
        attachments[AttachmentType.program].read_text().startswith('[Desktop Entry]\n')
    )
    assert 'Exec=true\n' in attachments[AttachmentType.program].read_text()
    assert attachments[AttachmentType.script].read_text().startswith('#!/bin/sh\n')
    if os.name != 'nt':
        assert not attachments[AttachmentType.script].stat().st_mode & 0o111
        assert not attachments[AttachmentType.program].stat().st_mode & 0o111
    assert (
        attachments[AttachmentType.image].read_bytes()
        == fallback_catalog.images[0].path.read_bytes()
    )
    assert (
        attachments[AttachmentType.video].read_bytes()
        == fallback_catalog.videos[0].path.read_bytes()
    )
    assert (
        attachments[AttachmentType.audio].read_bytes()
        == fallback_catalog.audio[0].path.read_bytes()
    )


def _check_pdf_offsets(raw: bytes) -> None:
    assert raw.startswith(b'%PDF-1.4\n')
    assert raw.endswith(b'%%EOF\n')
    offset = int(raw.split(b'startxref\n')[1].splitlines()[0])
    assert raw[offset : offset + 5] == b'xref\n'
    lines = raw[offset:].splitlines()
    count = int(lines[1].split()[1])
    for number, line in enumerate(lines[3 : count + 2], 1):
        object_offset = int(line.split()[0])
        assert raw[object_offset:].startswith(f'{number} 0 obj\n'.encode())


def _check_archive(path: Path) -> None:
    with ZipFile(path) as archive:
        assert archive.testzip() is None
        for item in archive.infolist():
            assert item.date_time == (2026, 1, 1, 0, 0, 0)
            if item.filename.endswith(('.xml', '.xhtml', '.opf', '.rels')):
                ET.fromstring(archive.read(item))  # noqa: S314 - locally generated fixture XML
        if path.suffix in {'.epub', '.odp'}:
            first = archive.infolist()[0]
            assert first.filename == 'mimetype'
            assert first.compress_type == ZIP_STORED


def test_font_has_valid_truetype_tables_and_checksum(fallback_catalog: AssetCatalog):
    path = next(
        item.path
        for item in fallback_catalog.attachments
        if item.file_type is AttachmentType.font
    )
    raw = path.read_bytes()
    assert raw[:4] == b'\x00\x01\x00\x00'
    count = int.from_bytes(raw[4:6], 'big')
    tables: dict[bytes, bytes] = {}
    for offset in range(12, 12 + count * 16, 16):
        tag, checksum, start, length = struct.unpack(
            '>4sIII', raw[offset : offset + 16]
        )
        tables[tag] = raw[start : start + length]
        if tag != b'head':
            assert _font_checksum(tables[tag]) == checksum
    assert {b'cmap', b'head', b'glyf', b'loca', b'hmtx', b'name'} <= tables.keys()
    assert _font_checksum(raw) == 0xB1B0AFBA


def _font_checksum(raw: bytes) -> int:
    raw += bytes((-len(raw)) % 4)
    return sum(item[0] for item in struct.iter_unpack('>I', raw)) % (2**32)


def test_fallback_reproduces_all_bytes_without_ffmpeg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    encoder = Mock(side_effect=AssertionError('Fallback must not invoke ffmpeg'))
    monkeypatch.setattr(assets, '_run_ffmpeg', encoder)
    first = create_assets(tmp_path / 'first', seed=123, backend=AssetBackend.fallback)
    second = create_assets(tmp_path / 'second', seed=123, backend=AssetBackend.fallback)
    assert _file_bytes(tmp_path / 'first') == _file_bytes(tmp_path / 'second')
    assert first.backend == second.backend == AssetBackend.fallback
    encoder.assert_not_called()


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob('*')
        if path.is_file()
    }


def test_auto_uses_fallback_when_ffmpeg_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(assets.shutil, 'which', Mock(return_value=None))
    assert create_assets(tmp_path / 'assets', seed=7).backend is AssetBackend.fallback


def test_requested_ffmpeg_is_not_silently_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(assets.shutil, 'which', Mock(return_value=None))
    with pytest.raises(RuntimeError, match='not installed'):
        create_assets(tmp_path / 'assets', seed=7, backend=AssetBackend.ffmpeg)
    assert not (tmp_path / 'assets').exists()


def test_installed_but_failing_ffmpeg_propagates_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(assets.shutil, 'which', Mock(return_value='/known/ffmpeg'))
    error = subprocess.CalledProcessError(1, ['ffmpeg'], stderr=b'encoder failure')
    encoder = Mock(side_effect=error)
    monkeypatch.setattr(assets, '_run_ffmpeg', encoder)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        create_assets(tmp_path / 'assets', seed=7)
    assert caught.value is error
    assert not list((tmp_path / 'assets').rglob('*.mp4'))


@pytest.mark.parametrize('seed', [-1, 2**32, True, False, '7', 3.5])
def test_invalid_seed_fails_before_writing(tmp_path: Path, seed: object):
    with pytest.raises(ValueError, match='unsigned 32-bit'):
        create_assets(
            tmp_path / 'assets', seed=cast('int', seed), backend=AssetBackend.fallback
        )
    assert not (tmp_path / 'assets').exists()


def test_existing_asset_directory_is_never_overwritten(tmp_path: Path):
    marker = tmp_path / 'preserve.txt'
    marker.write_text('preserve')
    with pytest.raises(FileExistsError):
        create_assets(tmp_path, seed=7, backend=AssetBackend.fallback)
    assert marker.read_text() == 'preserve'
