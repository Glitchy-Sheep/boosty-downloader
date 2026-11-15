"""Non-mutating schema preflight, including committed pages still in the WAL."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from shutil import copyfile
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Final

from boosty_downloader.infrastructure.library._db_engine import validate_database_path
from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError

if TYPE_CHECKING:
    from collections.abc import Generator

_SNAPSHOT_SUFFIXES: Final = ('', '-wal', '-journal')
_SNAPSHOT_ATTEMPTS: Final = 3


@dataclass(frozen=True, slots=True)
class _FileVersion:
    device: int
    inode: int
    size: int
    modified_ns: int
    changed_ns: int


def _file_version(path: Path) -> _FileVersion | None:
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    return _FileVersion(
        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns
    )


@contextmanager
def schema_snapshot(source: Path) -> Generator[Path, None, None]:
    """Inspect a stable private copy without creating sidecars beside the primary."""
    for _ in range(_SNAPSHOT_ATTEMPTS):
        with TemporaryDirectory(prefix='boosty-db-check-') as directory:
            snapshot = Path(directory).resolve() / source.name
            if _copy_stable_files(source, snapshot):
                yield snapshot
                return
    message = f'Library database changed during schema inspection: {source}. Stop other library processes and retry.'
    raise LibraryDatabaseError(message)


def _copy_stable_files(source: Path, snapshot: Path) -> bool:
    validate_database_path(source)
    paths = [source.with_name(source.name + suffix) for suffix in _SNAPSHOT_SUFFIXES]
    before = {path: _file_version(path) for path in paths}
    try:
        for path, version in before.items():
            if version is not None:
                copyfile(path, snapshot.with_name(path.name))
    except FileNotFoundError:
        return False
    validate_database_path(source)
    return before[source] is not None and before == {
        path: _file_version(path) for path in paths
    }
