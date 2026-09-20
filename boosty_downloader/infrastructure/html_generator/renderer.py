"""
Module provides functions to render HTML content from structured data.

You can also dump the rendered HTML to a file.

Current implementation uses Jinja2 templates to render HTML with a little styling.
"""

import mimetypes
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenAudio,
    HtmlGenChunk,
    HtmlGenFile,
    HtmlGenImage,
    HtmlGenList,
    HtmlGenText,
    HtmlGenUnavailable,
    HtmlGenVideo,
)
from boosty_downloader.infrastructure.human_readable_filesize import (
    human_readable_size,
)

# Load all templates as a package files
# So if ANY structure changed in this path - it should be reflected here.
# There is also a test to check if templates are rendered correctly (available).
env = Environment(
    loader=PackageLoader(
        'boosty_downloader.infrastructure.html_generator', 'templates'
    ),
    autoescape=select_autoescape(['html']),
    # Swallow the newlines and indentation of {% ... %} lines: without this
    # every template control line leaks blank lines into the rendered page.
    trim_blocks=True,
    lstrip_blocks=True,
)


def _media_src(url: str) -> str:
    """Media urls are file paths relative to the post folder: web slashes only."""
    return str(url).replace('\\', '/')


def _media_mime_type(url: str) -> str | None:
    """MIME by file extension; None omits the attribute so the browser sniffs."""
    mime_type, _ = mimetypes.guess_type(_media_src(url))
    return mime_type


# What an attachment card shows next to the name, by the file's MIME family.
_ICON_BY_MIME_FAMILY = {'video': '🎬', 'audio': '🎵', 'image': '🖼', 'text': '📄'}
_ARCHIVE_ICON = '📦'
_DOCUMENT_ICON = '📄'
_OTHER_FILE_ICON = '📎'
_ARCHIVE_MIME_TYPES = frozenset(
    {
        'application/zip',
        'application/gzip',
        'application/x-gzip',
        'application/x-tar',
        'application/x-7z-compressed',
        'application/x-rar-compressed',
        'application/vnd.rar',
        'application/x-bzip2',
        'application/x-xz',
    }
)
_DOCUMENT_MIME_PREFIXES = (
    'application/pdf',
    'application/rtf',
    'application/msword',
    'application/vnd.ms-',
    'application/vnd.openxmlformats-officedocument',
    'application/vnd.oasis.opendocument',
)

# A short extension the card can show as the file type: "MP4", "TAR.GZ" is
# not one of them, "2 (final)" from "v1.2 (final)" neither.
_TYPE_SUFFIX = re.compile(r'\.([A-Za-z0-9]{1,10})$')

_BYTES_PER_KB = 1024


@dataclass(frozen=True, slots=True)
class _AttachmentView:
    """One attachment card as the template shows it."""

    src: str
    name: str
    icon: str
    # "File · MP4 · 29.7 KB": the type and the size are there when known.
    meta: str


def _attachment_icon(filename: str) -> str:
    mime_type, _ = mimetypes.guess_type(filename)
    if mime_type is None:
        return _OTHER_FILE_ICON
    family = mime_type.split('/', 1)[0]
    if family in _ICON_BY_MIME_FAMILY:
        return _ICON_BY_MIME_FAMILY[family]
    if mime_type in _ARCHIVE_MIME_TYPES:
        return _ARCHIVE_ICON
    if mime_type.startswith(_DOCUMENT_MIME_PREFIXES):
        return _DOCUMENT_ICON
    return _OTHER_FILE_ICON


def _attachment_size(size: int | None) -> str | None:
    """Whole bytes below a kilobyte, one decimal above: "901 B", "29.7 KB"."""
    if size is None:
        return None
    if size < _BYTES_PER_KB:
        return f'{size} B'
    return human_readable_size(size, decimal_places=1)


def _attachment_view(file: HtmlGenFile) -> _AttachmentView:
    suffix = _TYPE_SUFFIX.search(file.filename)
    file_type = suffix.group(1).upper() if suffix else None
    meta = [part for part in ('File', file_type, _attachment_size(file.size)) if part]
    return _AttachmentView(
        src=_media_src(file.url),
        name=file.filename,
        icon=_attachment_icon(file.filename),
        meta=' · '.join(meta),
    )


def _render_attachments(files: Iterable[HtmlGenFile]) -> str:
    return env.get_template('attachments.html').render(
        files=[_attachment_view(file) for file in files]
    )


def _group_attachments(
    chunks: Iterable[HtmlGenChunk],
) -> Iterator[HtmlGenChunk | list[HtmlGenFile]]:
    """Neighbouring attachments share one block on the page; a run becomes one item."""
    run: list[HtmlGenFile] = []
    for chunk in chunks:
        if isinstance(chunk, HtmlGenFile):
            run.append(chunk)
            continue
        if run:
            yield run
            run = []
        yield chunk
    if run:
        yield run


def _unavailable_title(item: HtmlGenUnavailable) -> str:
    """'Video not downloaded: <title>' or, without a name, 'Image not downloaded'."""
    title = f'{item.kind.capitalize()} not downloaded'
    return f'{title}: {item.label}' if item.label else title


def render_html_chunk(chunk: HtmlGenChunk) -> str:  # noqa: PLR0911 - one template per chunk kind
    """Render a single HtmlGenChunk to its HTML representation."""
    match chunk:
        case HtmlGenText():
            return env.get_template('text.html').render(text=chunk)
        case HtmlGenImage():
            return env.get_template('image.html').render(
                image=chunk, src=_media_src(chunk.url)
            )
        case HtmlGenVideo():
            return env.get_template('video.html').render(
                video=chunk,
                src=_media_src(chunk.url),
                mime_type=_media_mime_type(chunk.url),
            )
        case HtmlGenAudio():
            return env.get_template('audio.html').render(
                audio=chunk, src=_media_src(chunk.url)
            )
        case HtmlGenList():
            return env.get_template('list.html').render(
                lst=chunk, render_chunk=render_html_chunk
            )
        case HtmlGenFile():
            return _render_attachments([chunk])
        case HtmlGenUnavailable():
            return env.get_template('unavailable.html').render(
                item=chunk, title=_unavailable_title(chunk)
            )


def render_html(chunks: list[HtmlGenChunk], page_title: str) -> str:
    """Render a list of HTML chunks to a full HTML page."""
    rendered = [
        _render_attachments(item) if isinstance(item, list) else render_html_chunk(item)
        for item in _group_attachments(chunks)
    ]
    # Empty chunks (e.g. text with no fragments) would otherwise leave
    # blank lines between their neighbours.
    parts = [part.strip('\n') for part in rendered if part.strip()]
    return env.get_template('base.html').render(
        content='\n'.join(parts), title=page_title
    )


def render_html_to_file(
    chunks: list[HtmlGenChunk], out_path: Path, page_title: str
) -> None:
    """Render HTML chunks to HTML file."""
    html = render_html(chunks, page_title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding='utf-8')
