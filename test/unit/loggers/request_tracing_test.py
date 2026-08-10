"""The debug log is attached to public issues - signed queries must not leak."""

from __future__ import annotations

from boosty_downloader.src.infrastructure.loggers.request_tracing import redacted_url


def test_redacted_url_drops_the_signed_query() -> None:
    """A logged CDN link with its query would hand out working credentials."""
    url = 'https://cdn.boosty.to/file/181ac169?sig=SECRET&expire=1770000000'

    assert redacted_url(url) == 'https://cdn.boosty.to/file/181ac169'


def test_redacted_url_keeps_a_plain_url_intact() -> None:
    """Over-cutting would make the log useless for matching failing endpoints."""
    url = 'https://api.boosty.to/v1/blog/author/post/'

    assert redacted_url(url) == url
