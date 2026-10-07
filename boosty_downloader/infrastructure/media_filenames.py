"""Shared media names for downloading and local file discovery."""

from typing import Final

from boosty_downloader.infrastructure.path_sanitizer import (
    MAX_NAME_BYTES,
    sanitize_filename,
)

# Video stems leave room for the extension reported by the server.
_GUESSED_EXTENSION_RESERVE_BYTES: Final = 8


def boosty_video_filename(title: str, video_id: str) -> str:
    """Build a video stem with its short ID and room for an extension."""
    return sanitize_filename(
        title.strip() or 'video',
        suffix=f' ({video_id[:8]})',
        max_bytes=MAX_NAME_BYTES - _GUESSED_EXTENSION_RESERVE_BYTES,
    )
