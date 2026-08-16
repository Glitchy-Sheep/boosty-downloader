"""
Module provides functions to render HTML content from structured data.

You can also dump the rendered HTML to a file.

Current implementation uses Jinja2 templates to render HTML with a little styling.
"""

import mimetypes
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from boosty_downloader.src.infrastructure.html_generator.models import (
    HtmlGenAudio,
    HtmlGenChunk,
    HtmlGenFile,
    HtmlGenImage,
    HtmlGenList,
    HtmlGenText,
    HtmlGenVideo,
)

# Load all templates as a package files
# So if ANY structure changed in this path - it should be reflected here.
# There is also a test to check if templates are rendered correctly (available).
env = Environment(
    loader=PackageLoader(
        'boosty_downloader.src.infrastructure.html_generator', 'templates'
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


def render_html_chunk(chunk: HtmlGenChunk) -> str:
    """Render a single HtmlGenChunk to its HTML representation."""
    match chunk:
        case HtmlGenText():
            return env.get_template('text.html').render(text=chunk)
        case HtmlGenImage():
            return env.get_template('image.html').render(image=chunk)
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
            return env.get_template('file.html').render(file=chunk)


def render_html(chunks: list[HtmlGenChunk], page_title: str) -> str:
    """Render a list of HTML chunks to a full HTML page."""
    rendered = [render_html_chunk(chunk) for chunk in chunks]
    return env.get_template('base.html').render(
        content='\n'.join(rendered), title=page_title
    )


def render_html_to_file(
    chunks: list[HtmlGenChunk], out_path: Path, page_title: str
) -> None:
    """Render HTML chunks to HTML file."""
    html = render_html(chunks, page_title)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding='utf-8')
