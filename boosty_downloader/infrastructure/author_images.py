"""Refresh owned author images without exposing incomplete or failed downloads."""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from enum import Enum
from stat import S_ISDIR, S_ISREG
from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.file_downloader import (
    DownloadError,
    copy_download_response,
    download_errors,
    open_download_response,
    response_filename,
)
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.library._record_paths import (
    check_containment,
    get_author_folder,
)
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_SERVICE_FOLDER,
)
from boosty_downloader.infrastructure.media_workspace import (
    cleanup_owned_workspaces,
    temporary_owned_workspace,
)
from boosty_downloader.infrastructure.media_writer import open_media_writer

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from aiohttp import ClientResponse
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
    with _image_errors(url), ExitStack() as stack:
        _image_folder(library_root, author)
        async with open_download_response(session, url) as response:
            filename = response_filename(response, kind.value)
            destination = _create_image_destination(library_root, author, filename)
            directory = _enter_workspace(stack, destination, kind)
            source = directory / 'download.tmp'
            await _write_image(response, source, filename)
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


def _enter_workspace(
    stack: ExitStack, destination: Path, kind: AuthorImageKind
) -> Path:
    owner_id = f'author-image:{kind.value}'
    cleanup_owned_workspaces(destination.parent, owner_id=owner_id)
    return stack.enter_context(
        temporary_owned_workspace(destination.parent, owner_id=owner_id)
    )


async def _write_image(response: ClientResponse, source: Path, filename: str) -> None:
    async with open_media_writer(source) as writer:
        await copy_download_response(response, writer.write, filename=filename)


def _publish_image(
    source: Path, destination: Path, *, library_root: Path, author: str
) -> None:
    if _image_destination(library_root, author, destination.name) != destination:
        message = 'Author image destination changed during the download'
        raise ValueError(message)
    source.replace(destination)


@contextmanager
def _image_errors(url: str) -> Generator[None, None, None]:
    try:
        with download_errors(url):
            yield
    except ValueError as error:
        message = 'Invalid author image destination or URL'
        raise DownloadError(message, file=None, resource_url=url) from error
