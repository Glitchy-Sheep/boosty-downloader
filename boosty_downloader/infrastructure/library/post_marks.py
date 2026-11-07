"""Read and atomically save user marks without changing downloaded content."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from boosty_downloader.domain.library_marks import PostMarks
from boosty_downloader.infrastructure.library._atomic_write import write_atomically
from boosty_downloader.infrastructure.library._record_paths import check_containment
from boosty_downloader.infrastructure.library._viewer_json import (
    decode_viewer_record,
    encode_viewer_record,
)
from boosty_downloader.infrastructure.library.author_records import read_locked_posts
from boosty_downloader.infrastructure.library.errors import InvalidViewerRecordError
from boosty_downloader.infrastructure.library.post_records import JsonPostRecords

if TYPE_CHECKING:
    from pathlib import Path

VIEWER_RECORD_FILENAME: Final = 'viewer.json'


class JsonPostMarks:
    """User marks for one fixed library root, with fresh folder lookup and reads."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    def get_marks(self, author: str, post_id: str) -> PostMarks | None:
        """Read independent marks for a known post, or None for an unknown one."""
        path = self._find_marks_path(author, post_id)
        if path is not None:
            return _read_marks(path, author, post_id)
        if post_id in read_locked_posts(self._root, author):
            return PostMarks()
        return None

    def save_marks(self, author: str, post_id: str, marks: PostMarks) -> None:
        """Replace marks in a confirmed saved folder; missing ownership raises LookupError."""
        path = self._find_marks_path(author, post_id)
        if path is None:
            message = f'No confirmed saved folder for {author}/{post_id}'
            raise LookupError(message)
        _read_marks(path, author, post_id)
        try:
            data = encode_viewer_record(author, post_id, marks)
        except InvalidViewerRecordError as error:
            message = f'{path}: {error}'
            raise type(error)(message) from error
        write_atomically(path, data)

    def _find_marks_path(self, author: str, post_id: str) -> Path | None:
        located = JsonPostRecords(self._root).find_post(author, post_id)
        if located is None or located.record is None:
            return None
        folder = self._root / located.folder
        check_containment(self._root, folder)
        path = folder / VIEWER_RECORD_FILENAME
        check_containment(self._root, path)
        return path


def _read_marks(path: Path, author: str, post_id: str) -> PostMarks:
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return PostMarks()
    try:
        return decode_viewer_record(data, author=author, post_id=post_id)
    except InvalidViewerRecordError as error:
        message = f'{path}: {error}'
        raise type(error)(message) from error
