"""Save bounded raster thumbnails without replacing original post images."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from pathlib import PurePosixPath
from stat import S_ISREG
from typing import TYPE_CHECKING, Final
from urllib.parse import unquote_plus, urlsplit, urlunsplit

from boosty_downloader.infrastructure.file_downloader import (
    DownloadError,
    open_download_response,
)
from boosty_downloader.infrastructure.image_transfer import (
    enter_image_workspace,
    image_errors,
    write_image_response,
)
from boosty_downloader.infrastructure.library._media_paths import is_link
from boosty_downloader.infrastructure.library._record_paths import get_author_folder
from boosty_downloader.infrastructure.media_output_paths import (
    resolve_media_destination,
)
from boosty_downloader.infrastructure.post_images import (
    ImageLocation,
    create_image_destination,
    publish_image,
)
from boosty_downloader.infrastructure.raster_headers import inspect_raster_header

if TYPE_CHECKING:
    from pathlib import Path

    from aiohttp import ClientResponse
    from aiohttp_retry import RetryClient

MAX_THUMBNAIL_WIDTH: Final = 480
MAX_THUMBNAIL_BYTES: Final = 2 * 1024 * 1024
_DIRECTORY: Final = '.boosty-downloader/thumbs'
_RESIZE_FIELDS: Final = frozenset({'mw', 'mh', 'croped'})
_CONTENT_TYPES: Final = {
    '.png': {'image/png'},
    '.jpg': {'image/jpeg', 'image/pjpeg'},
    '.gif': {'image/gif'},
    '.webp': {'image/webp'},
}


@dataclass(frozen=True, slots=True)
class ThumbnailFile:
    """A complete temporary thumbnail and its inspected raster extension."""

    source: Path
    extension: str


def build_thumbnail_url(url: str) -> str:
    """Replace resize fields, keeping every other query component byte-for-byte."""
    parts = urlsplit(url)
    if parts.scheme not in {'http', 'https'} or not parts.hostname:
        message = 'Thumbnail URL must use HTTP or HTTPS'
        raise ValueError(message)
    fields = (
        [
            field
            for field in parts.query.split('&')
            if unquote_plus(field.partition('=')[0]) not in _RESIZE_FIELDS
        ]
        if parts.query
        else []
    )
    fields.append(f'mw={MAX_THUMBNAIL_WIDTH}')
    return urlunsplit(parts._replace(query='&'.join(fields)))


async def download_post_thumbnail(  # noqa: PLR0913 - Full post-local media identity.
    *,
    session: RetryClient,
    library_root: Path,
    author: str,
    post_id: str,
    media_id: str,
    url: str,
) -> str:
    """Return an author-relative thumbnail path for a current post image."""
    with image_errors(url, label='Post thumbnail'):
        location = _thumbnail_location(
            library_root, author, ('image', post_id, media_id)
        )
        return await _download_thumbnail(session, url, location)


async def download_teaser_thumbnail(
    *,
    session: RetryClient,
    library_root: Path,
    author: str,
    post_id: str,
    url: str,
) -> str:
    """Return a locked teaser thumbnail with an independent ownership identity."""
    with image_errors(url, label='Teaser thumbnail'):
        location = _thumbnail_location(library_root, author, ('teaser', post_id))
        return await _download_thumbnail(session, url, location)


def has_thumbnail(library_root: Path, author: str, path: str | None) -> bool:
    """Observe one ordinary nonempty thumbnail without writes or folder scans."""
    if path is None:
        return False
    _check_author(library_root, author)
    if str(PurePosixPath(path).parent) != _DIRECTORY:
        message = 'Thumbnail must be directly under the author thumbnail directory'
        raise ValueError(message)
    target = resolve_media_destination(library_root, author, path)
    try:
        info = target.lstat()
    except FileNotFoundError:
        return False
    return S_ISREG(info.st_mode) and not is_link(info) and info.st_size > 0


def _thumbnail_location(
    root: Path, author: str, identity: tuple[str, ...]
) -> ImageLocation:
    _check_author(root, author)
    if not all(identity):
        message = 'Thumbnail identities must be nonempty'
        raise ValueError(message)
    stem = sha256(dumps(identity, ensure_ascii=True).encode()).hexdigest()
    return ImageLocation(root, author, _DIRECTORY, stem, f'thumbnail:{stem}')


def _check_author(root: Path, author: str) -> None:
    folder = get_author_folder(root.resolve(), author)
    try:
        info = folder.lstat()
    except FileNotFoundError:
        return
    if is_link(info):
        message = 'Thumbnail author must be an ordinary directory'
        raise ValueError(message)


async def _download_thumbnail(
    session: RetryClient, url: str, location: ImageLocation
) -> str:
    resized_url = build_thumbnail_url(url)
    with ExitStack() as stack:
        location.resolve(location.stem)
        async with open_download_response(
            session, resized_url, encoded_url=True
        ) as response:
            thumbnail = await _read_thumbnail(response, stack, location, url)
        filename = f'{location.stem}{thumbnail.extension}'
        destination = create_image_destination(location, filename)
        published = publish_image(thumbnail.source, destination, filename, location)
    return f'{location.directory}/{published.name}'


async def _read_thumbnail(
    response: ClientResponse, stack: ExitStack, location: ImageLocation, url: str
) -> ThumbnailFile:
    placeholder = create_image_destination(location, f'{location.stem}.tmp')
    directory = enter_image_workspace(
        stack, placeholder.parent, owner_id=location.owner_id
    )
    source = directory / 'download.tmp'
    await write_image_response(
        response, source, location.stem, max_bytes=MAX_THUMBNAIL_BYTES
    )
    extension = _thumbnail_extension(source, response.headers.get('Content-Type'), url)
    return ThumbnailFile(source=source, extension=extension)


def _thumbnail_extension(source: Path, content_type: str | None, url: str) -> str:
    try:
        header = inspect_raster_header(source.read_bytes())
    except ValueError as error:
        message = 'Thumbnail has an unrecognized or malformed raster header'
        raise DownloadError(message, file=None, resource_url=url) from error
    if header.width > MAX_THUMBNAIL_WIDTH:
        message = 'Thumbnail response exceeds the requested width'
        raise DownloadError(message, file=None, resource_url=url)
    mime = content_type.partition(';')[0].strip().lower() if content_type else ''
    if (
        mime
        and mime != 'application/octet-stream'
        and mime not in _CONTENT_TYPES[header.extension]
    ):
        message = 'Thumbnail content type contradicts its raster format'
        raise DownloadError(message, file=None, resource_url=url)
    return header.extension
