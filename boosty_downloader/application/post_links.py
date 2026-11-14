"""Resolve authored Boosty post links without choosing a storage implementation."""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import quote, unquote, urlsplit

from boosty_downloader.domain.library import PostIdentity
from boosty_downloader.domain.library_errors import LibraryReadError
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import ListBlock, TextBlock

if TYPE_CHECKING:
    from boosty_downloader.application.ports import LinkResolver
    from boosty_downloader.domain.stored_post import Block, ListItem, StoredPost

_INVALID_PERCENT: Final = re.compile(r'%(?![0-9a-fA-F]{2})')
_SUFFIX_START: Final = re.compile(r'[?#]')
_POST_HOST: Final = 'boosty.to'
_POST_SCHEMES: Final = frozenset({'http', 'https'})


@dataclass(frozen=True, slots=True)
class PostLink:
    """A complete post identity and the original query/fragment suffix."""

    identity: PostIdentity
    suffix: str = ''


def _has_controls(value: str) -> bool:
    return any(not character.isprintable() for character in value)


def _decode_component(value: str) -> str | None:
    try:
        decoded = unquote(value, errors='strict')
    except UnicodeDecodeError:
        return None
    if (
        not decoded
        or decoded in {'.', '..'}
        or decoded != decoded.strip()
        or _has_controls(decoded)
        or any(character in decoded for character in '/\\')
    ):
        return None
    return decoded


def _post_identity(path: str) -> PostIdentity | None:
    match path.split('/'):
        case ['', author_component, 'posts', id_component]:
            author = _decode_component(author_component)
            post_id = _decode_component(id_component)
        case _:
            return None
    if author is None or post_id is None:
        return None
    return PostIdentity(author, post_id)


def parse_post_link(href: str) -> PostLink | None:
    """Recognize exact Boosty post URLs without normalizing ambiguous spellings."""
    if (
        _has_controls(href)
        or any(character.isspace() for character in href)
        or '\\' in href
        or _INVALID_PERCENT.search(href)
    ):
        return None
    try:
        parsed = urlsplit(href)
    except ValueError:
        return None
    if parsed.scheme not in _POST_SCHEMES or parsed.netloc.lower() != _POST_HOST:
        return None
    identity = _post_identity(parsed.path)
    if identity is None:
        return None
    suffix = _SUFFIX_START.search(href)
    return PostLink(identity, href[suffix.start() :] if suffix else '')


def has_post_links(record: StoredPost) -> bool:
    """Identify pages whose authored links may change as the library grows."""
    return any(_block_has_post_links(block) for block in record.blocks)


def _block_has_post_links(block: Block) -> bool:
    match block:
        case TextBlock():
            return _text_has_post_links(block)
        case ListBlock():
            return any(_item_has_post_links(item) for item in block.items)
        case _:
            return False


def _text_has_post_links(block: TextBlock) -> bool:
    for fragment in block.fragments:
        match fragment:
            case PostDataChunkText.TextFragment(link_url=str(href)):
                if parse_post_link(href) is not None:
                    return True
            case _:
                continue
    return False


def _item_has_post_links(item: ListItem) -> bool:
    return any(_block_has_post_links(block) for block in item.data) or any(
        _item_has_post_links(nested) for nested in item.nested_items
    )


def _is_library_folder(folder: str) -> bool:
    parts = folder.split('/')
    return (
        '/' in folder
        and not _has_controls(folder)
        and not any(character in folder for character in '\\:')
        and all(part and part not in {'.', '..'} for part in parts)
    )


def _target_folder(resolver: LinkResolver, identity: PostIdentity) -> str | None:
    try:
        folder = resolver.post_folder(identity.author, identity.post_id)
    except LibraryReadError:
        return None
    if (
        folder is None
        or not _is_library_folder(folder)
        or folder.partition('/')[0] != identity.author
    ):
        return None
    return folder


class ViewerPostLinks:
    """Build viewer routes for targets with a saved body, keeping other links remote."""

    def __init__(self, resolver: LinkResolver) -> None:
        self._resolver = resolver

    def __call__(self, href: str) -> str:
        link = parse_post_link(href)
        if link is None or _target_folder(self._resolver, link.identity) is None:
            return href
        author = quote(link.identity.author, safe='')
        post_id = quote(link.identity.post_id, safe='')
        return f'/a/{author}/p/{post_id}{link.suffix}'


class SavedPostLinks:
    """Resolve one saved page's links and remember targets still unavailable."""

    def __init__(self, resolver: LinkResolver, source_folder: str) -> None:
        if not _is_library_folder(source_folder):
            message = 'A saved post source needs a portable library-relative folder'
            raise ValueError(message)
        self._resolver = resolver
        self._source_folder = source_folder
        self._unresolved: set[PostIdentity] = set()

    @property
    def unresolved(self) -> frozenset[PostIdentity]:
        """Independent identities of recognized links left on Boosty in this page."""
        return frozenset(self._unresolved)

    def __call__(self, href: str) -> str:
        link = parse_post_link(href)
        if link is None:
            return href
        folder = _target_folder(self._resolver, link.identity)
        if folder is None:
            self._unresolved.add(link.identity)
            return href
        relative = posixpath.relpath(f'/{folder}/post.html', f'/{self._source_folder}')
        return quote(relative, safe='/') + link.suffix
