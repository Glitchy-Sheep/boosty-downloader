"""Small standalone pages shown when the library or UI is unavailable."""

from dataclasses import dataclass
from html import escape


@dataclass(frozen=True, slots=True)
class LibraryNotice:
    """Plain-text explanation shown instead of the library interface."""

    title: str
    message: str


def notice_page(notice: LibraryNotice, *, address: str | None = None) -> str:
    """Escape local paths and diagnostics before putting them in a page."""
    link = ''
    if address is not None:
        safe_address = escape(address, quote=True)
        link = f'<p><a href="{safe_address}">{safe_address}</a></p>'
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<title>{escape(notice.title)}</title>'
        '<style>body{max-width:48rem;margin:4rem auto;padding:0 1.5rem;'
        'font:1rem/1.6 system-ui,sans-serif;color-scheme:light dark}'
        'p{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>'
        f'<h1>{escape(notice.title)}</h1><p>{escape(notice.message)}</p>'
        f'{link}</body></html>'
    )
