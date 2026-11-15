import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import pytest

from boosty_downloader.infrastructure.library._db_errors import LibraryDatabaseError
from boosty_downloader.infrastructure.library.db_initialization import (
    initialize_database_library,
)
from boosty_downloader.infrastructure.library.db_library_format import (
    database_library_paths,
)
from boosty_downloader.infrastructure.library.db_store import LibraryDatabase

_CRASH_SCRIPT = """
import sys
import time
from pathlib import Path
from boosty_downloader.infrastructure.library import _db_marker_files, db_initialization, db_store
from boosty_downloader.infrastructure.library.db_library_format import database_library_paths

root, phase, barrier = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])

def stop():
    barrier.write_text('ready')
    while True:
        time.sleep(1)

publish = _db_marker_files.publish_completed_file
def interrupted_publish(source, destination):
    if destination.name == 'initialization.json' and phase == 'before-receipt':
        stop()
    if destination.name == 'library.json' and phase == 'ready-temporary':
        stop()
    result = publish(source, destination)
    if destination.name == 'initialization.json' and phase == 'after-receipt':
        stop()
    return result
_db_marker_files.publish_completed_file = interrupted_publish

if phase == 'partial-database':
    db_store.create_schema = lambda *_args: stop()
if phase == 'before-ready':
    db_initialization._publish_ready = lambda *_args: stop()

db_initialization.initialize_database_library(database_library_paths(root))
"""

_INITIALIZE_SCRIPT = """
import sys
from pathlib import Path
from boosty_downloader.infrastructure.library.db_initialization import initialize_database_library
from boosty_downloader.infrastructure.library.db_library_format import database_library_paths
print(initialize_database_library(database_library_paths(Path(sys.argv[1]))), flush=True)
"""


@dataclass(frozen=True, slots=True)
class _FileState:
    data: bytes
    modified_ns: int


def _files(root: Path) -> dict[str, _FileState]:
    return {
        path.relative_to(root).as_posix(): _FileState(
            path.read_bytes(), path.stat().st_mtime_ns
        )
        for path in root.rglob('*')
        if path.is_file()
    }


def _kill_at_boundary(root: Path, phase: str, barrier: Path) -> None:
    with subprocess.Popen(  # noqa: S603 - trusted script and pytest-owned paths
        [sys.executable, '-c', _CRASH_SCRIPT, str(root), phase, str(barrier)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        deadline = time.monotonic() + 10
        try:
            while not barrier.exists():
                if process.poll() is not None:
                    stdout, stderr = process.communicate(timeout=2)
                    pytest.fail(
                        f'Initializer exited before {phase}: {stdout}\n{stderr}'
                    )
                if time.monotonic() >= deadline:
                    pytest.fail(f'Initializer did not reach {phase}')
                time.sleep(0.01)
        finally:
            process.kill()
            process.communicate(timeout=5)
        assert process.returncode != 0


@pytest.mark.parametrize(
    ('phase', 'resumable'),
    [
        ('before-receipt', False),
        ('after-receipt', True),
        ('partial-database', False),
        ('before-ready', True),
        ('ready-temporary', False),
    ],
)
def test_process_kill_resumes_only_proven_owned_complete_state(
    tmp_path: Path, phase: str, *, resumable: bool
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    _kill_at_boundary(paths.root, phase, tmp_path / 'barrier')
    assert not paths.marker.exists()
    before = _files(paths.root)
    if resumable:
        expected = UUID(json.loads(paths.initialization.read_bytes())['library_id'])
        assert initialize_database_library(paths) == expected
        assert LibraryDatabase.inspect(paths.database).library_id == expected
        assert paths.marker.exists()
    else:
        with pytest.raises(LibraryDatabaseError):
            initialize_database_library(paths)
        assert _files(paths.root) == before
        assert not paths.marker.exists()


def test_cache_location_cannot_change_after_receipt_survives_process_kill(
    tmp_path: Path,
):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    _kill_at_boundary(paths.root, 'after-receipt', tmp_path / 'barrier')
    changed = database_library_paths(paths.root, tmp_path.resolve() / 'new-cache')
    before = _files(paths.root)
    with pytest.raises(LibraryDatabaseError, match='another database location'):
        initialize_database_library(changed)
    assert not changed.database.parent.exists()
    assert _files(paths.root) == before
    initialize_database_library(paths)


def test_concurrent_initializers_publish_only_one_identity(tmp_path: Path):
    paths = database_library_paths(tmp_path.resolve() / 'library')
    arguments = [sys.executable, '-c', _INITIALIZE_SCRIPT, str(paths.root)]
    processes: list[subprocess.Popen[str]] = []
    identities: set[UUID] = set()
    try:
        for _ in range(3):
            processes.append(  # noqa: PERF401 - retain every started child for cleanup
                subprocess.Popen(  # noqa: S603 - trusted script and pytest-owned path
                    arguments, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
            )
        for process in processes:
            stdout, stderr = process.communicate(timeout=15)
            if process.returncode == 0:
                identities.add(UUID(stdout.strip()))
            else:
                assert 'Error' in stderr
        assert identities
        library_id = initialize_database_library(paths)
        assert identities == {library_id}
        assert LibraryDatabase.inspect(paths.database).library_id == library_id
        assert not list(paths.marker.parent.glob('*.tmp'))
        assert not paths.database.with_name('library.db.bak').exists()
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)
