"""Author-relative references to thumbnails stored alongside library records."""

from pathlib import PureWindowsPath

from boosty_downloader.domain.path_names import sanitize_filename
from boosty_downloader.infrastructure.library._record_validation import (
    validate_relative_file_path,
)


def validate_thumbnail_path(value: str | None, name: str) -> None:
    """Require one portable filename directly inside the author's thumbnail folder."""
    if value is None:
        return
    validate_relative_file_path(value, name)
    folder, _, filename = value.rpartition('/')
    if (
        folder != '.boosty-downloader/thumbs'
        or sanitize_filename(filename) != filename
        or PureWindowsPath(filename).is_reserved()
    ):
        message = f'{name} must name a portable file in .boosty-downloader/thumbs/'
        raise ValueError(message)
