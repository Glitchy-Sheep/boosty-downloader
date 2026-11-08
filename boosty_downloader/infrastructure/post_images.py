"""Publish complete post previews and locked teasers without replacing other files."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import PurePosixPath
from stat import S_ISREG
from typing import TYPE_CHECKING, Final
from unicodedata import normalize

from boosty_downloader.domain.stored_post import MediaKind
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
from boosty_downloader.infrastructure.library._record_paths import get_author_folder
from boosty_downloader.infrastructure.library.author_records import (
    AUTHOR_SERVICE_FOLDER,
)
from boosty_downloader.infrastructure.media_output_paths import (
    create_media_parent,
    resolve_media_destination,
)
from boosty_downloader.infrastructure.media_publication import publish_completed_file
from boosty_downloader.infrastructure.path_sanitizer import (
    compose_filename,
    sanitize_filename,
)

if TYPE_CHECKING:
    from collections.abc import Collection
    from pathlib import Path

    from aiohttp_retry import RetryClient

_PREVIEW_DIRECTORY: Final = 'previews'
_TEASER_DIRECTORY: Final = f'{AUTHOR_SERVICE_FOLDER}/teasers'


@dataclass(frozen=True, slots=True)
class _ImageLocation:
    library_root: Path
    folder: str
    directory: str
    stem: str
    owner_id: str
    reserved_keys: frozenset[str] = frozenset()

    def resolve(self, filename: str) -> Path:
        return resolve_media_destination(
            self.library_root, self.folder, f'{self.directory}/{filename}'
        )


async def download_post_preview(  # noqa: PLR0913 - Transfer inputs and post-wide reservations.
    *,
    session: RetryClient,
    library_root: Path,
    post_folder: str,
    media_id: str,
    url: str,
    reserved_paths: Collection[str] = (),
) -> str:
    """
    Download a video preview and return its post-relative path.

    The caller ensures this preview needs downloading and excludes concurrent transfers of the same media ID. Occupied names and reserved post-relative paths are preserved, including the parent directories of missing files recorded for other media.
    """
    with image_errors(url, label='Post image'):
        location = _ImageLocation(
            library_root,
            post_folder,
            _PREVIEW_DIRECTORY,
            _video_id(media_id),
            f'preview:{media_id}',
            _preview_reserved_keys(reserved_paths),
        )
        return await _download_image(session, url, location)


async def download_locked_teaser(
    *,
    session: RetryClient,
    library_root: Path,
    author: str,
    post_id: str,
    url: str,
) -> str:
    """
    Download a locked post's teaser and return its author-relative path.

    The caller excludes concurrent transfers of this post's teaser. Occupied names remain untouched.
    """
    with image_errors(url, label='Post image'):
        location = _teaser_location(library_root, author, post_id)
        return await _download_image(session, url, location)


def has_locked_teaser(library_root: Path, author: str, path: str | None) -> bool:
    """Check one saved teaser without scanning folders or following image links."""
    if path is None:
        return False
    get_author_folder(library_root.resolve(), author)
    target = resolve_media_destination(library_root, author, path)
    try:
        info = target.lstat()
    except FileNotFoundError:
        return False
    return S_ISREG(info.st_mode) and not is_link(info) and info.st_size > 0


def _teaser_location(library_root: Path, author: str, post_id: str) -> _ImageLocation:
    get_author_folder(library_root.resolve(), author)
    return _ImageLocation(
        library_root,
        author,
        _TEASER_DIRECTORY,
        _safe_identity(post_id),
        f'teaser:{post_id}',
    )


def _video_id(media_id: str) -> str:
    prefix = f'{MediaKind.boosty_video.value}:'
    if not media_id.startswith(prefix):
        message = 'Video previews require a Boosty video identity'
        raise ValueError(message)
    return _safe_identity(media_id.removeprefix(prefix))


def _safe_identity(value: str) -> str:
    if not value or sanitize_filename(value, max_bytes=len(value.encode())) != value:
        message = 'Image identity must be a portable filename'
        raise ValueError(message)
    return value


async def _download_image(
    session: RetryClient, url: str, location: _ImageLocation
) -> str:
    with ExitStack() as stack:
        location.resolve(location.stem)
        async with open_download_response(session, url) as response:
            filename = response_filename(response, location.stem)
            destination = _create_destination(location, filename)
            directory = enter_image_workspace(
                stack, destination.parent, owner_id=location.owner_id
            )
            source = directory / 'download.tmp'
            await write_image_response(response, source, filename)
        require_image_bytes(source, url)
        published = _publish_image(source, destination, filename, location)
    return f'{location.directory}/{published.name}'


def _path_key(path: str) -> str:
    return normalize('NFC', path).casefold()


def _preview_reserved_keys(reserved_paths: Collection[str]) -> frozenset[str]:
    reserved = frozenset(_path_key(path) for path in reserved_paths)
    directory = PurePosixPath(_path_key(_PREVIEW_DIRECTORY))
    if any(str(parent) in reserved for parent in (directory, *directory.parents)):
        message = 'Preview directory overlaps a reserved media file'
        raise ValueError(message)
    blocked = set(reserved)
    for path in reserved:
        blocked.update(str(parent) for parent in PurePosixPath(path).parents)
    return frozenset(blocked)


def _free_filename(location: _ImageLocation, filename: str) -> str:
    source = PurePosixPath(filename)
    candidate = filename
    suffix = 0
    while True:
        target = location.resolve(candidate)
        if _path_key(f'{location.directory}/{candidate}') not in location.reserved_keys:
            try:
                target.lstat()
            except FileNotFoundError:
                return candidate
        suffix += 1
        candidate = compose_filename(
            source.stem, extension=source.suffix, marker=f' ({suffix})'
        )


def _create_destination(location: _ImageLocation, filename: str) -> Path:
    while True:
        free_name = _free_filename(location, filename)
        try:
            return create_media_parent(
                location.library_root,
                location.folder,
                f'{location.directory}/{free_name}',
            )
        except FileExistsError:
            continue


def _publish_image(
    source: Path, destination: Path, filename: str, location: _ImageLocation
) -> Path:
    while True:
        current = location.resolve(destination.name)
        if current != destination or current.parent != source.parent.parent:
            message = 'Image destination changed during the download'
            raise ValueError(message)
        try:
            return publish_completed_file(source, destination).path
        except FileExistsError:
            destination = _create_destination(location, filename)
