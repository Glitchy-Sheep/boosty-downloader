"""Refresh owned author images without exposing incomplete or failed downloads."""

from __future__ import annotations

from contextlib import ExitStack
from enum import Enum
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.file_downloader import (
    open_download_response,
    response_filename,
)
from boosty_downloader.infrastructure.image_transfer import (
    enter_image_workspace,
    image_errors,
    require_image_bytes,
    write_image_response,
)
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.library._record_paths import (
    check_containment,
    get_author_folder,
)
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_SERVICE_FOLDER,
)

if TYPE_CHECKING:
    from pathlib import Path

    from aiohttp_retry import RetryClient


class AuthorImageKind(str, Enum):
    """Stable image roles owned by the author's library service folder."""

    avatar = 'avatar'
    cover = 'cover'


async def download_author_image(
    *,
    session: RetryClient,
    library_root: Path,
    author: str,
    kind: AuthorImageKind,
    url: str,
) -> str:
    """
    Return an author-relative path after atomically publishing a complete image.

    An existing regular file for the same role and extension is replaced. Other files and earlier extensions remain untouched. The caller excludes concurrent refreshes of this author's image role.
    """
    with image_errors(url, label='Author image'), ExitStack() as stack:
        _image_folder(library_root, author)
        async with open_download_response(session, url) as response:
            filename = response_filename(response, kind.value)
            destination = _create_image_destination(library_root, author, filename)
            directory = enter_image_workspace(
                stack, destination.parent, owner_id=f'author-image:{kind.value}'
            )
            source = directory / 'download.tmp'
            await write_image_response(response, source, filename)
        require_image_bytes(source, url)
        _publish_image(source, destination, library_root=library_root, author=author)
    return f'{AUTHOR_SERVICE_FOLDER}/{filename}'


def _create_image_destination(library_root: Path, author: str, filename: str) -> Path:
    destination = _image_destination(library_root, author, filename)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return _image_destination(library_root, author, filename)


def _image_folder(library_root: Path, author: str) -> Path:
    root = library_root.resolve()
    author_folder = get_author_folder(root, author).resolve()
    folder = author_folder / AUTHOR_SERVICE_FOLDER
    _require_directory(folder)
    check_containment(author_folder, folder)
    return folder


def _image_destination(library_root: Path, author: str, filename: str) -> Path:
    destination = _image_folder(library_root, author) / filename
    _require_replaceable(destination)
    return destination


def _require_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if is_link(info) or not S_ISDIR(info.st_mode):
        message = f'Author image parent must be an ordinary directory: {path}'
        raise ValueError(message)


def _require_replaceable(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if is_link(info) or not S_ISREG(info.st_mode):
        message = f'Author image destination must be an ordinary file: {path}'
        raise ValueError(message)


def _publish_image(
    source: Path, destination: Path, *, library_root: Path, author: str
) -> None:
    if _image_destination(library_root, author, destination.name) != destination:
        message = 'Author image destination changed during the download'
        raise ValueError(message)
    source.replace(destination)
