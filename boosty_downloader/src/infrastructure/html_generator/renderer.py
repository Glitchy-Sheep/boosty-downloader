from pathlib import Path
from typing import Any

from jinja2 import Environment, PackageLoader, select_autoescape

from boosty_downloader.src.application.mappers.external_video_content import (
    PostDataChunkExternalVideo,
)
from boosty_downloader.src.domain.post import (
    PostDataChunkImage,
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.src.domain.post_data_chunks import (
    PostDataChunkBoostyVideo,
    PostDataChunkFile,
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


def render_chunk(chunk: Any) -> str:
    if isinstance(chunk, PostDataChunkText):
        return env.get_template('text.html').render(text=chunk)
    if isinstance(chunk, PostDataChunkImage):
        return env.get_template('image.html').render(image=chunk)
    if isinstance(chunk, PostDataChunkBoostyVideo) or isinstance(
        chunk, PostDataChunkExternalVideo
    ):
        return env.get_template('video.html').render(video=chunk)
    if isinstance(chunk, PostDataChunkTextualList):
        return env.get_template('list.html').render(
            lst=chunk, render_chunk=render_chunk
        )
    if isinstance(chunk, PostDataChunkFile):
        return f'<a href="{chunk.url}" download>{chunk.filename}</a>'
    return '<!-- Unknown chunk -->'


def render_post(chunks: list[Any]) -> str:
    rendered = [render_chunk(chunk) for chunk in chunks]
    return env.get_template('base.html').render(content='\n'.join(rendered))


def render_post_to_file(chunks: list[Any], out_path: Path) -> None:
    html = render_post(chunks)  # использует твою функцию render_post()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding='utf-8')
