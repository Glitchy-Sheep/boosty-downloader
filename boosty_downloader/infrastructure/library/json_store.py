"""Read and atomically publish the record in one known post folder."""

import os
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final

from boosty_downloader.domain.stored_post import StoredPost
from boosty_downloader.infrastructure.library._post_json import (
    decode_post_record,
    encode_post_record,
)
from boosty_downloader.infrastructure.library.errors import InvalidPostRecordError

POST_RECORD_FILENAME: Final = 'post.json'


def read_post_record(post_folder: Path) -> StoredPost | None:
    """Read a saved record; a missing file returns None without creating folders."""
    post_file = post_folder / POST_RECORD_FILENAME
    try:
        data = post_file.read_bytes()
    except FileNotFoundError:
        return None
    try:
        return decode_post_record(data)
    except InvalidPostRecordError as error:
        message = f'{post_file}: {error}'
        raise type(error)(message) from error


def write_post_record(
    post_folder: Path, record: StoredPost, *, create_folder: bool = False
) -> None:
    """Validate a record before optionally creating its folder and saving atomically."""
    post_file = post_folder / POST_RECORD_FILENAME
    try:
        data = encode_post_record(record)
    except InvalidPostRecordError as error:
        message = f'{post_file}: {error}'
        raise type(error)(message) from error
    if create_folder:
        post_folder.mkdir(parents=True, exist_ok=True)
    _write_atomically(post_file, data)


def _write_atomically(post_file: Path, data: bytes) -> None:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode='wb',
            dir=post_file.parent,
            prefix=f'{post_file.name}.',
            suffix='.tmp',
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(data)
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(post_file)
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
