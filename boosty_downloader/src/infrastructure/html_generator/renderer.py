"""
Module provides functions to render HTML content from structured data.

You can also dump the rendered HTML to a file.

Current implementation uses Jinja2 templates to render HTML with a little styling.
"""

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
)


def render_html_chunk(chunk: HtmlGenChunk) -> str:
    """Render a single HtmlGenChunk to its HTML representation."""
    match chunk:
        case HtmlGenText():
            return env.get_template('text.html').render(text=chunk)
        case HtmlGenImage():
            return env.get_template('image.html').render(image=chunk)
        case HtmlGenVideo():
            chunk.url = str(chunk.url).replace('\\', '/')
            return env.get_template('video.html').render(video=chunk)
        case HtmlGenAudio():
            chunk.url = str(chunk.url).replace('\\', '/')
            return env.get_template('audio.html').render(audio=chunk)
        case HtmlGenList():
            return env.get_template('list.html').render(
                lst=chunk, render_chunk=render_html_chunk
            )
        case HtmlGenFile():
            return f'<a href="{chunk.url}" download>{chunk.filename}</a>'


def render_html(chunks: list[HtmlGenChunk]) -> str:
    """Render a list of HTML chunks to HTML."""
    rendered = [render_html_chunk(chunk) for chunk in chunks]
    return env.get_template('base.html').render(content='\n'.join(rendered))


def render_html_to_file(chunks: list[HtmlGenChunk], out_path: Path) -> None:
    """Render HTML chunks to HTML file."""
    html = render_html(chunks)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding='utf-8')
