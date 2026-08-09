"""Regression tests for #75: downloads keep their extensions and never get .bin."""

from __future__ import annotations

from boosty_downloader.src.infrastructure.file_downloader import _extension_to_append


def test_octet_stream_never_replaces_a_real_extension() -> None:
    """The live #75 case: the server serves an .m4a file as 'unknown bytes'."""
    assert (
        _extension_to_append('Песня-присциллы.m4a', 'application/octet-stream') is None
    )


def test_octet_stream_never_invents_bin() -> None:
    """'Type unknown' teaches nothing - an extensionless name stays as is."""
    assert _extension_to_append('noname', 'application/octet-stream') is None


def test_a_lying_server_cannot_replace_an_extension() -> None:
    """A misconfigured server saying text/html must not turn report.pdf into .html."""
    assert _extension_to_append('report.pdf', 'text/html') is None


def test_extensionless_video_gets_an_extension_from_content_type() -> None:
    """Video filenames carry no extension - the informative content type adds one."""
    assert _extension_to_append('My stream (a2dd6942)', 'video/mp4') == '.mp4'


def test_a_dot_inside_a_title_is_not_an_extension() -> None:
    """with_suffix used to truncate 'Ep. 5 (id)' to 'Ep.mp4' - append keeps the name."""
    assert _extension_to_append('Ep. 5 (b3ee7053)', 'video/mp4') == '.mp4'
