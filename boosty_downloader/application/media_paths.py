"""
Pure file discovery and name allocation within one post folder.

Paths use portable relative strings. Callers reserve every retained media path before processing current pieces. A snapshot distinguishes regular files from other occupied names; it must never report an I/O failure as a missing file.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath
from typing import TYPE_CHECKING
from unicodedata import normalize

from yarl import URL

from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkAudio,
    PostDataChunkBoostyVideo,
    PostDataChunkFile,
    PostDataChunkImage,
)
from boosty_downloader.domain.stored_post import MediaKind
from boosty_downloader.infrastructure.media_filenames import boosty_video_filename
from boosty_downloader.infrastructure.path_sanitizer import (
    compose_filename,
    sanitize_filename,
)

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping
    from collections.abc import Set as AbstractSet

    from boosty_downloader.application.mappers.live_post import LiveMedia
    from boosty_downloader.domain.disk_snapshot import DiskSnapshot
    from boosty_downloader.domain.stored_post import StoredPost


@dataclass(frozen=True)
class MediaPathHint:
    """A preferred relative name, or a complete stem awaiting Content-Type."""

    path: str
    suffix_from_response: bool = False


@dataclass(frozen=True)
class FileMatch:
    """An observed file's actual path and size in bytes."""

    path: str
    size: int


@dataclass(frozen=True, slots=True)
class _PathCandidate:
    """A generated path and its position in the collision-name family."""

    number: int
    path: str


@dataclass(frozen=True, order=True)
class _FileCandidate:
    """A file ranked by generated-name priority, then its actual path and size."""

    candidate_number: int
    path: str
    size: int


def get_preferred_media_path(media_id: str, media: LiveMedia) -> MediaPathHint | None:
    """Derive a discovery hint from downloader names, including unfinished uploads."""
    match media.download:
        case PostDataChunkImage():
            return _image_path_hint(media.download)
        case PostDataChunkFile():
            return _author_path_hint(media.download.filename, 'files')
        case PostDataChunkAudio():
            return _author_path_hint(media.download.title, 'audio')
        case PostDataChunkBoostyVideo():
            return _video_path_hint(media.download.title, media.download.id)
        case _:
            return _unfinished_path_hint(media_id, media)


def _unfinished_path_hint(media_id: str, media: LiveMedia) -> MediaPathHint | None:
    match media.kind:
        case MediaKind.file:
            return _author_path_hint(media.filename, 'files')
        case MediaKind.audio:
            return _author_path_hint(media.title, 'audio')
        case MediaKind.boosty_video:
            return _video_path_hint(media.title, media_id.split(':', 1)[1])
        case MediaKind.image | MediaKind.external_video:
            return None


def _image_path_hint(image: PostDataChunkImage) -> MediaPathHint:
    name = URL(image.url).name
    # Encoded slashes belong to the filename, not to the folder layout.
    return MediaPathHint(
        path=f'images/{sanitize_filename(name)}', suffix_from_response=True
    )


def _author_path_hint(name: str | None, subdir: str) -> MediaPathHint | None:
    if name is None:
        return None
    basename = PurePosixPath(name).name
    if not basename:
        basename = compose_filename(basename)
    return MediaPathHint(path=f'{subdir}/{basename}')


def _video_path_hint(title: str | None, video_id: str) -> MediaPathHint | None:
    if title is None:
        return None
    name = boosty_video_filename(title, video_id)
    return MediaPathHint(path=f'boosty_videos/{name}', suffix_from_response=True)


def get_media_alias_queries(
    hints: Mapping[str, MediaPathHint], disk: DiskSnapshot
) -> set[str]:
    """
    Build concrete alternate spellings for filesystem identity checks.

    Matching spelling only identifies a query. Recovery still requires a confirmed alias in the snapshot.
    """
    by_folder: dict[str, list[str]] = {}
    for path in disk.files:
        if not _is_temporary(path):
            folder = _path_key(str(PurePosixPath(path).parent))
            by_folder.setdefault(folder, []).append(path)
    queries: set[str] = set()
    for media_id, hint in hints.items():
        if media_id.startswith(f'{MediaKind.external_video.value}:'):
            continue
        folder = _path_key(str(PurePosixPath(hint.path).parent))
        queries.update(
            _candidate_alias_queries(
                hint, _identity_token(media_id), by_folder.get(folder, ())
            )
        )
    return queries


def _candidate_alias_queries(
    hint: MediaPathHint, token: str, paths: Collection[str]
) -> set[str]:
    queries: set[str] = set()
    for path in paths:
        key = _path_key(path)
        for candidate in _candidate_paths(path, hint, token, fold_markers=True):
            if (
                candidate.path != path
                and not _is_temporary(candidate.path)
                and _path_key(candidate.path) == key
            ):
                queries.add(candidate.path)
    return queries


def get_media_path_reservations(
    record: StoredPost, *, exclude_preview_for: str | None = None
) -> dict[str, str]:
    """Reserve retained primary and preview paths, including missing/removed files."""
    reservations = {
        media_id: entry.path
        for media_id, entry in record.media.items()
        if entry.path is not None
    }
    reservations.update(
        {
            _preview_owner_id(media_id): entry.preview_path
            for media_id, entry in record.media.items()
            if entry.preview_path is not None and media_id != exclude_preview_for
        }
    )
    return reservations


def _preview_owner_id(media_id: str) -> str:
    """Keep preview ownership separate from kind-prefixed primary media IDs."""
    return f'preview:{media_id}'


def reserve_media_path(
    preferred_path: str,
    media_id: str,
    disk: DiskSnapshot,
    reservations: Mapping[str, str],
) -> str:
    """
    Choose a free concrete path without changing the snapshot or reservations.

    The caller supplies the resolved extension/title and records the returned path before writing bytes. Other pieces' reservations and every occupied name block reuse. NFC and case folding avoid collisions when a library moves between supported filesystems.
    """
    occupied = {
        _path_key(path) for path in (*disk.files, *disk.occupied, *disk.aliases)
    }
    retained_paths = {
        _path_key(path) for owner, path in reservations.items() if owner != media_id
    }
    if _has_reserved_parent(preferred_path, retained_paths):
        message = 'A retained media file reserves the output directory'
        raise ValueError(message)
    occupied.update(_include_parent_paths(retained_paths))
    hint = MediaPathHint(preferred_path)
    token = _identity_token(media_id)
    number = 0
    while True:
        candidate = _candidate_path(hint, token, number)
        if _path_key(candidate) not in occupied:
            return candidate
        number += 1


def find_media_file(  # noqa: PLR0913 - discovery needs both stored and live file hints
    media_id: str,
    disk: DiskSnapshot,
    reservations: Mapping[str, str],
    *,
    recorded_path: str | None = None,
    preferred: MediaPathHint | None = None,
    expected_size: int | None = None,
) -> FileMatch | None:
    """Find a plausible unclaimed file, including numbered names after gaps."""
    retained_paths = {
        _path_key(spelling)
        for owner, path in reservations.items()
        if owner != media_id
        for spelling in (path, disk.aliases.get(path, path))
    }
    blocked = _include_parent_paths(retained_paths)
    if recorded_path is not None and not _is_path_reserved(
        recorded_path, retained_paths, blocked
    ):
        recorded = find_recorded_file(recorded_path, disk)
        if (
            recorded is not None
            and not _is_path_reserved(recorded.path, retained_paths, blocked)
            and _is_plausible(recorded.size, expected_size)
        ):
            return recorded
    if preferred is None or media_id.startswith(f'{MediaKind.external_video.value}:'):
        return None
    token = _identity_token(media_id)
    matches: list[_FileCandidate] = []
    for path in dict.fromkeys((*disk.files, *disk.aliases)):
        found = find_recorded_file(path, disk)
        if found is None:
            continue
        if (
            _is_path_reserved(path, retained_paths, blocked)
            or _is_path_reserved(found.path, retained_paths, blocked)
            or not _is_plausible(found.size, expected_size)
        ):
            continue
        number = _candidate_number(path, preferred, token)
        if number is not None:
            matches.append(
                _FileCandidate(
                    candidate_number=number, path=found.path, size=found.size
                )
            )
    if not matches:
        return None
    best = min(matches)
    return FileMatch(path=best.path, size=best.size)


def find_recorded_file(path: str, disk: DiskSnapshot) -> FileMatch | None:
    """Read an owned file from the snapshot, including zero or changed sizes."""
    actual = path if path in disk.files else disk.aliases.get(path, path)
    if _is_temporary(path) or _is_temporary(actual) or actual not in disk.files:
        return None
    return FileMatch(path=actual, size=disk.files[actual])


def _candidate_path(
    hint: MediaPathHint,
    token: str,
    number: int,
    observed_suffix: str = '',
) -> str:
    path = PurePosixPath(hint.path)
    stem = path.name if hint.suffix_from_response else path.stem
    suffix = observed_suffix if hint.suffix_from_response else path.suffix
    marker = (
        '' if number == 0 else f' ({token})' if number == 1 else f' ({token}-{number})'
    )
    name = compose_filename(stem, extension=suffix, marker=marker)
    return str(path.with_name(name))


def _candidate_number(path: str, hint: MediaPathHint, token: str) -> int | None:
    for candidate in _candidate_paths(path, hint, token):
        if path == candidate.path:
            return candidate.number
    return None


def _candidate_paths(
    path: str, hint: MediaPathHint, token: str, *, fold_markers: bool = False
) -> Iterator[_PathCandidate]:
    observed = PurePosixPath(path)
    suffixes = ('', observed.suffix) if hint.suffix_from_response else ('',)
    name, marker_token = observed.name, token
    if fold_markers:
        name, marker_token = _path_key(name), _path_key(marker_token)
    marker = rf' \({re.escape(marker_token)}(?:-([2-9]|[1-9][0-9]+))?\)'
    numbers = [0] + [
        int(match[1]) if match[1] is not None else 1
        for match in re.finditer(marker, name)
    ]
    for number in sorted(set(numbers)):
        for suffix in suffixes:
            yield _PathCandidate(number, _candidate_path(hint, token, number, suffix))


def _identity_token(media_id: str) -> str:
    kind_value, source_id = media_id.split(':', 1)
    if kind_value == MediaKind.external_video.value:
        return sha256(source_id.encode('utf-8')).hexdigest()[:8]
    return source_id[:8]


def _include_parent_paths(paths: AbstractSet[str]) -> set[str]:
    """Reserve each retained file's required directories against file publication."""
    parents = {parent for path in paths for parent in _parent_paths(path)}
    return set(paths) | parents


def _has_reserved_parent(path: str, reservations: AbstractSet[str]) -> bool:
    return any(parent in reservations for parent in _parent_paths(path))


def _is_path_reserved(
    path: str, reservations: AbstractSet[str], blocked: AbstractSet[str]
) -> bool:
    return _path_key(path) in blocked or _has_reserved_parent(path, reservations)


def _parent_paths(path: str) -> Iterator[str]:
    for parent in PurePosixPath(_path_key(path)).parents:
        if parent.parts:
            yield str(parent)


def _path_key(path: str) -> str:
    return normalize('NFC', path).casefold()


def _is_temporary(path: str) -> bool:
    return any(
        part.startswith('.') and part.endswith('.part')
        for part in PurePosixPath(path).parts
    )


def _is_plausible(size: int, expected_size: int | None) -> bool:
    return size > 0 and (expected_size is None or size == expected_size)
