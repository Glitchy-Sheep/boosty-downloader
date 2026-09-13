"""Regression tests for #75: "type unknown" must never produce an extension.

Names built by the app (videos, images) have no extension by construction -
the content type appends one, and 'application/octet-stream' teaches
nothing, so ".bin" files are never born. Which names ask for an extension
at all is pinned in test/unit/post_media_downloader.
"""

from __future__ import annotations

from boosty_downloader.infrastructure.file_downloader import _extension_to_append


def test_type_unknown_never_produces_an_extension() -> None:
    """'application/octet-stream' means "bytes" - .bin must not be born from it."""
    assert _extension_to_append('application/octet-stream') is None
    assert _extension_to_append(None) is None


def test_informative_content_type_gives_the_extension() -> None:
    assert _extension_to_append('video/mp4') == '.mp4'
    assert _extension_to_append('image/png') == '.png'
