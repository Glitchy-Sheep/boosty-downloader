"""Atomic publication of library record bytes."""

import os
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile


def write_atomically(path: Path, data: bytes) -> None:
    """Publish complete bytes through a temporary file beside the destination."""
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode='wb',
            dir=path.parent,
            prefix=f'{path.name}.',
            suffix='.tmp',
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
