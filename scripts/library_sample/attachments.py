"""Small valid attachment examples, including inert program and script samples."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from library_sample.asset_models import (
    AttachmentAsset,
    AttachmentType,
    AudioAsset,
    ImageAsset,
    VideoAsset,
)

if TYPE_CHECKING:
    from collections.abc import Callable

_XML: Final = '<?xml version="1.0" encoding="UTF-8"?>'
_ZIP_TIME: Final = (2026, 1, 1, 0, 0, 0)
_FALLBACK_DIR: Final = Path(__file__).parent / 'fallback_assets'


@dataclass(frozen=True, slots=True)
class _GeneratedAttachment:
    kind: AttachmentType
    name: str
    write: Callable[[Path], None]


@dataclass(frozen=True, slots=True)
class _CopiedAttachment:
    kind: AttachmentType
    name: str
    source: Path


def create_attachments(
    directory: Path,
    *,
    images: tuple[ImageAsset, ...],
    videos: tuple[VideoAsset, ...],
    audio: tuple[AudioAsset, ...],
) -> tuple[AttachmentAsset, ...]:
    """Write one example of each category; generated programs are never executed."""
    target = directory / 'attachments'
    target.mkdir()
    assets: dict[AttachmentType, AttachmentAsset] = {}
    for spec in _generated_attachments():
        path = target / spec.name
        spec.write(path)
        assets[spec.kind] = AttachmentAsset(path, spec.kind)
    for source in _copied_attachments(images, videos, audio):
        path = target / source.name
        shutil.copyfile(source.source, path)
        assets[source.kind] = AttachmentAsset(path, source.kind)
    return tuple(assets[kind] for kind in AttachmentType)


def _generated_attachments() -> tuple[_GeneratedAttachment, ...]:
    return (
        _GeneratedAttachment(
            AttachmentType.pdf, 'Заметки к уроку, часть 1.pdf', _write_pdf
        ),
        _GeneratedAttachment(AttachmentType.document, 'Lyrics.docx', _write_docx),
        _GeneratedAttachment(AttachmentType.book, 'Chapter 1.epub', _write_epub),
        _GeneratedAttachment(AttachmentType.slides, 'Workshop.odp', _write_slides),
        _GeneratedAttachment(AttachmentType.sheet, 'Prices.csv', _write_sheet),
        _GeneratedAttachment(AttachmentType.archive, 'Stems.zip', _write_archive),
        _GeneratedAttachment(AttachmentType.model, 'Figurine.stl', _write_model),
        _GeneratedAttachment(AttachmentType.code, 'Theme.json', _write_code),
        _GeneratedAttachment(AttachmentType.program, 'Sample.desktop', _write_program),
        _GeneratedAttachment(AttachmentType.script, 'Sample.command', _write_script),
        _GeneratedAttachment(AttachmentType.other, 'Palette.sample', _write_other),
    )


def _copied_attachments(
    images: tuple[ImageAsset, ...],
    videos: tuple[VideoAsset, ...],
    audio: tuple[AudioAsset, ...],
) -> tuple[_CopiedAttachment, ...]:
    return (
        _CopiedAttachment(
            AttachmentType.image, f'Wallpaper{images[0].path.suffix}', images[0].path
        ),
        _CopiedAttachment(
            AttachmentType.audio, f'Full mix{audio[0].path.suffix}', audio[0].path
        ),
        _CopiedAttachment(AttachmentType.video, 'Timelapse.mp4', videos[0].path),
        _CopiedAttachment(
            AttachmentType.font,
            'SampleSymbols.ttf',
            _FALLBACK_DIR / 'SampleSymbols.ttf',
        ),
    )


def _write_zip(path: Path, parts: dict[str, str]) -> None:
    with ZipFile(path, 'w') as output:
        for name, content in parts.items():
            info = ZipInfo(name, _ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = ZIP_STORED if name == 'mimetype' else ZIP_DEFLATED
            output.writestr(info, content.encode('utf-8'))


def _write_pdf(path: Path) -> None:
    stream = b'BT /F1 24 Tf 72 720 Td (A synthetic viewer guide) Tj ET'
    objects = [
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
        b'<< /Length %d >>\nstream\n%b\nendstream' % (len(stream), stream),
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    ]
    path.write_bytes(_pdf_bytes(objects))


def _pdf_bytes(objects: list[bytes]) -> bytes:
    output = bytearray(b'%PDF-1.4\n')
    offsets: list[int] = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(output))
        output += b'%d 0 obj\n%b\nendobj\n' % (number, body)
    xref = len(output)
    output += b'xref\n0 %d\n0000000000 65535 f \n' % (len(objects) + 1)
    output += b''.join(b'%010d 00000 n \n' % offset for offset in offsets)
    output += b'trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n' % (
        len(objects) + 1,
        xref,
    )
    return bytes(output)


def _write_docx(path: Path) -> None:
    _write_zip(
        path,
        {
            '[Content_Types].xml': _XML
            + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
            '_rels/.rels': _XML
            + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
            'word/document.xml': _XML
            + '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{escape("Synthetic lyrics & workshop notes")}</w:t></w:r></w:p></w:body></w:document>',
        },
    )


def _write_epub(path: Path) -> None:
    title = escape('Глава 1: музыка & цвет')
    _write_zip(
        path,
        {
            'mimetype': 'application/epub+zip',
            'META-INF/container.xml': _XML
            + '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            'OEBPS/content.opf': _XML
            + '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:identifier id="id">urn:uuid:00000000-0000-4000-8000-000000000001</dc:identifier>'
            f'<dc:title>{title}</dc:title><dc:language>ru</dc:language>'
            '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
            '<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
            '<item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="chapter"/></spine></package>',
            'OEBPS/nav.xhtml': _XML
            + '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
            f'<head><title>{title}</title></head><body><nav epub:type="toc"><ol>'
            f'<li><a href="chapter.xhtml">{title}</a></li></ol></nav></body></html>',
            'OEBPS/chapter.xhtml': _XML + '<html xmlns="http://www.w3.org/1999/xhtml">'
            f'<head><title>{title}</title></head><body><h1>{title}</h1><p>Синтетическая книга для просмотрщика.</p></body></html>',
        },
    )


def _write_slides(path: Path) -> None:
    _write_zip(
        path,
        {
            'mimetype': 'application/vnd.oasis.opendocument.presentation',
            'META-INF/manifest.xml': _XML
            + '<manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2">'
            '<manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.presentation"/>'
            '<manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/></manifest:manifest>',
            'content.xml': _XML
            + '<office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
            'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" office:version="1.2">'
            '<office:body><office:presentation><draw:page draw:name="Workshop">'
            '<draw:frame svg:x="2cm" svg:y="2cm" svg:width="20cm" svg:height="5cm"><draw:text-box>'
            '<text:p>Синтетический мастер-класс</text:p></draw:text-box></draw:frame>'
            '</draw:page></office:presentation></office:body></office:document-content>',
        },
    )


def _write_sheet(path: Path) -> None:
    path.write_text('Tier,Price\nFree,0\nSupporter,300\n', encoding='utf-8')


def _write_archive(path: Path) -> None:
    _write_zip(path, {'readme.txt': 'Synthetic stems for the viewer sample.\n'})


def _write_model(path: Path) -> None:
    vertices = ('0 0 0', '20 0 0', '0 20 0', '0 0 20')
    lines = ['solid figurine']
    for face in ((0, 2, 1), (0, 1, 3), (0, 3, 2), (1, 2, 3)):
        lines.extend(('  facet normal 0 0 0', '    outer loop'))
        lines.extend(f'      vertex {vertices[index]}' for index in face)
        lines.extend(('    endloop', '  endfacet'))
    lines.append('endsolid figurine')
    path.write_text('\n'.join(lines) + '\n', encoding='ascii')


def _write_code(path: Path) -> None:
    path.write_text('{"accent": "#7c9cff"}\n', encoding='utf-8')


def _write_program(path: Path) -> None:
    path.write_text(
        '[Desktop Entry]\nType=Application\nName=Harmless sample\nExec=true\nTerminal=false\n',
        encoding='utf-8',
    )


def _write_script(path: Path) -> None:
    path.write_text(
        '#!/bin/sh\nprintf "A synthetic viewer sample\\n"\n', encoding='utf-8'
    )


def _write_other(path: Path) -> None:
    path.write_text('Sample palette\n#7c9cff\n#c9a4ef\n', encoding='utf-8')
