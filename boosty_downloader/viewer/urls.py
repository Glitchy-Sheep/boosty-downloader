"""Portable library paths and their once-encoded local media addresses."""

from urllib.parse import quote

from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.viewer.media_paths import is_author_component


def _check_relative(path: str) -> None:
    if any(part in {'', '.', '..'} for part in path.split('/')) or any(
        char in path for char in '\\\x00'
    ):
        message = 'The library contains an invalid relative path.'
        raise LibraryReadError(message)


def author_relative_path(author: str, path: str | None) -> str | None:
    """Remove exactly the requested author's component from a library path."""
    if path is None:
        return None
    name, separator, relative = path.partition('/')
    if not separator or name != author:
        message = 'The library path belongs to another author.'
        raise LibraryReadError(message)
    _check_relative(relative)
    return relative


def post_media_path(author: str, folder: str, path: str) -> str:
    """Join a post-relative filename to its validated author-relative folder."""
    relative = author_relative_path(author, folder)
    _check_relative(path)
    return f'{relative}/{path}'


def media_url(author: str, relative: str) -> str:
    """Encode stored Unicode names once, including literal percent characters."""
    if not is_author_component(author):
        message = 'The library contains an invalid author name.'
        raise LibraryReadError(message)
    _check_relative(relative)
    return f'/media/{quote(author, safe="")}/{quote(relative, safe="/")}'
