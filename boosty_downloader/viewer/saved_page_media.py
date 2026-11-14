"""Grant a saved page narrowly scoped access to its embedded local media."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from html import escape, unescape
from html.parser import HTMLParser
from typing import Final, TypeAlias
from urllib.parse import quote, unquote, urlsplit

from boosty_downloader.viewer.media_paths import is_author_component

EMBED_TOKEN_PARAMETER: Final = 'embed'  # noqa: S105 - query parameter name
_TOKEN_PATTERN: Final = re.compile(r'[0-9a-f]{64}')
_INVALID_PERCENT: Final = re.compile(r'%(?![0-9a-fA-F]{2})')
_INVALID_PATH_TEXT: Final = re.compile(r'[\x00-\x1f\x7f\ud800-\udfff]')
_TAG_START: Final = re.compile(r'<[^\s/>]+')
_ATTRIBUTE: Final = re.compile(
    r"""\s+(?P<name>[^\s=/>"'<>`]+)"""
    r"""(?:\s*=\s*(?:"(?P<double>[^"]*)"|'(?P<single>[^']*)'|"""
    r"""(?P<bare>[^\s"'=<>`]+)))?"""
)
_MEDIA_ATTRIBUTES: Final = {
    'img': frozenset({'src'}),
    'audio': frozenset({'src'}),
    'video': frozenset({'src', 'poster'}),
    'source': frozenset({'src'}),
}
_TEXT_ELEMENTS: Final = frozenset(
    {
        'script',
        'style',
        'textarea',
        'title',
        'xmp',
        'iframe',
        'noembed',
        'noframes',
        'noscript',
        'plaintext',
    }
)
_ParsedAttributes: TypeAlias = list[tuple[str, str | None]]


def _has_invalid_path_text(value: str) -> bool:
    return _INVALID_PATH_TEXT.search(value) is not None


def _is_relative_path(value: str) -> bool:
    return (
        bool(value)
        and not _has_invalid_path_text(value)
        and not any(char in value for char in '\\:')
        and all(part not in {'', '.', '..'} for part in value.split('/'))
    )


def _is_identity(author: str, relative: str) -> bool:
    return (
        is_author_component(author)
        and not _has_invalid_path_text(author)
        and _is_relative_path(relative)
    )


class SavedMediaAccess:
    """Sign one decoded resource identity for this application instance only."""

    def __init__(self) -> None:
        self._key = secrets.token_bytes(32)

    def token_for(self, author: str, relative: str) -> str:
        """Issue a token; filesystem containment and media type are checked on use."""
        if not _is_identity(author, relative):
            message = 'A saved-media token requires a canonical resource identity'
            raise ValueError(message)
        identity = f'boosty.saved-media.v1\0{author}\0{relative}'.encode()
        return hmac.new(self._key, identity, hashlib.sha256).hexdigest()

    def is_allowed(self, author: str, relative: str, token: str) -> bool:
        """Reject malformed, retargeted and other application instances' tokens."""
        if not _TOKEN_PATTERN.fullmatch(token) or not _is_identity(author, relative):
            return False
        return hmac.compare_digest(self.token_for(author, relative), token)


def _local_media_path(value: str) -> str | None:
    if not value or value != value.strip() or _has_invalid_path_text(value):
        return None
    if _INVALID_PERCENT.search(value) or any(char in value for char in '\\?#'):
        return None
    try:
        parsed = urlsplit(value)
    except ValueError:
        return None
    if parsed.scheme or parsed.netloc or parsed.path.startswith('/'):
        return None
    return _decoded_media_path(parsed.path)


def _decoded_media_path(path: str) -> str | None:
    try:
        parts = [unquote(part, errors='strict') for part in path.split('/')]
    except UnicodeDecodeError:
        return None
    if any('/' in part or not _is_relative_path(part) for part in parts):
        return None
    return '/'.join(parts)


@dataclass(frozen=True, slots=True)
class _Attribute:
    name: str
    value: str | None
    start: int
    end: int
    quoted: bool


@dataclass(frozen=True, slots=True)
class _Replacement:
    start: int
    end: int
    text: str


def _read_attribute(match: re.Match[str]) -> _Attribute:
    for group in ('double', 'single', 'bare'):
        value = match.group(group)
        if value is not None:
            return _Attribute(
                match['name'].lower(),
                unescape(value),
                match.start(group),
                match.end(group),
                group != 'bare',
            )
    return _Attribute(
        match['name'].lower(), None, match.end(), match.end(), quoted=False
    )


def _read_attributes(raw: str, parsed: _ParsedAttributes) -> list[_Attribute] | None:
    prefix = _TAG_START.match(raw)
    if prefix is None or len({name for name, _ in parsed}) != len(parsed):
        return None
    attributes: list[_Attribute] = []
    position = prefix.end()
    while match := _ATTRIBUTE.match(raw, position):
        attributes.append(_read_attribute(match))
        position = match.end()
    if raw[position:].strip() not in {'>', '/>'}:
        return None
    if [(item.name, item.value) for item in attributes] != parsed:
        return None
    return attributes


class _MediaRewriter(HTMLParser):
    def __init__(
        self, html: str, author: str, folder: str, access: SavedMediaAccess
    ) -> None:
        super().__init__(convert_charrefs=False)
        self._author = author
        self._folder = folder
        self._access = access
        self._line_starts = [0, *(match.end() for match in re.finditer('\n', html))]
        self._text_element: str | None = None
        self.replacements: list[_Replacement] = []

    def handle_starttag(self, tag: str, attrs: _ParsedAttributes) -> None:
        if self._text_element is not None:
            return
        if tag in _TEXT_ELEMENTS:
            self._text_element = tag
            return
        allowed = _MEDIA_ATTRIBUTES.get(tag)
        if allowed is None:
            return
        raw = self.get_starttag_text()
        if raw is not None:
            self._rewrite_tag(raw, attrs, allowed)

    def _rewrite_tag(
        self, raw: str, attrs: _ParsedAttributes, allowed: frozenset[str]
    ) -> None:
        attributes = _read_attributes(raw, attrs)
        if attributes is None:
            return
        line, column = self.getpos()
        offset = self._line_starts[line - 1] + column
        for attribute in attributes:
            if attribute.name in allowed:
                self._rewrite_attribute(attribute, offset)

    def handle_startendtag(self, tag: str, attrs: _ParsedAttributes) -> None:
        # HTML raw-text elements ignore a self-closing slash.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._text_element and tag != 'plaintext':
            self._text_element = None

    def _rewrite_attribute(self, attribute: _Attribute, offset: int) -> None:
        path = _local_media_path(attribute.value or '')
        if path is None:
            return
        relative = f'{self._folder}/{path}'
        token = self._access.token_for(self._author, relative)
        encoded = quote(f'{self._author}/{relative}', safe='/')
        value = escape(f'/media/{encoded}?{EMBED_TOKEN_PARAMETER}={token}', quote=True)
        if not attribute.quoted:
            value = f'"{value}"'
        self.replacements.append(
            _Replacement(offset + attribute.start, offset + attribute.end, value)
        )


def rewrite_saved_page(
    html: str, *, author: str, relative: str, access: SavedMediaAccess
) -> str:
    """Adapt local media attributes without changing stored HTML or anchor links."""
    folder, separator, filename = relative.rpartition('/')
    if not separator or filename != 'post.html' or not _is_identity(author, relative):
        return html
    parser = _MediaRewriter(html, author, folder, access)
    parser.feed(html)
    parser.close()
    parts: list[str] = []
    position = 0
    for replacement in parser.replacements:
        parts.extend((html[position : replacement.start], replacement.text))
        position = replacement.end
    parts.append(html[position:])
    return ''.join(parts)
