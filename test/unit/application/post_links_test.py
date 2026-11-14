"""Authored post links resolve full identities while retaining remote fallbacks."""

from dataclasses import dataclass, field
from urllib.parse import quote

import pytest

from boosty_downloader.application.post_links import (
    PostLink,
    SavedPostLinks,
    ViewerPostLinks,
    parse_post_link,
)
from boosty_downloader.domain.library import PostIdentity
from boosty_downloader.domain.library_errors import LibraryReadError

_FIRST = PostIdentity('author', 'abcdef01-first-full-id')
_SECOND = PostIdentity('author', 'abcdef01-second-full-id')
_FIRST_URL = f'https://boosty.to/{_FIRST.author}/posts/{_FIRST.post_id}'
_SECOND_URL = f'https://boosty.to/{_SECOND.author}/posts/{_SECOND.post_id}'


@dataclass
class _Resolver:
    folders: dict[PostIdentity, str] = field(default_factory=dict[PostIdentity, str])
    calls: list[PostIdentity] = field(default_factory=list[PostIdentity])
    error: Exception | None = None

    def post_folder(self, author: str, post_id: str) -> str | None:
        self.calls.append(PostIdentity(author, post_id))
        if self.error is not None:
            raise self.error
        return self.folders.get(PostIdentity(author, post_id))


@pytest.mark.parametrize('prefix', ['http://boosty.to', 'HTTPS://BOOSTY.TO'])
@pytest.mark.parametrize('suffix', ['', '?', '#', '?#', '?q=%20&x=1#section?part'])
def test_parser_preserves_full_identity_and_original_suffix(
    prefix: str, suffix: str
) -> None:
    href = f'{prefix}/{_FIRST.author}/posts/{_FIRST.post_id}{suffix}'

    assert parse_post_link(href) == PostLink(_FIRST, suffix)


def test_components_are_decoded_once_without_assuming_uuid_ids() -> None:
    href = 'https://boosty.to/%D0%90%D0%B2%D1%82%D0%BE%D1%80/posts/opaque%252F%23id'

    assert parse_post_link(href) == PostLink(PostIdentity('Автор', 'opaque%2F#id'))


@pytest.mark.parametrize(
    'href',
    [
        '../another/post.html',
        '/author/posts/id',
        '//boosty.to/author/posts/id',
        'https://example.com/author/posts/id',
        'https://boosty.to.example/author/posts/id',
        'https://www.boosty.to/author/posts/id',
        'https://booſty.to/author/posts/id',
        'https://boosty.to./author/posts/id',
        'https://boosty.to:443/author/posts/id',
        'https://user@boosty.to/author/posts/id',
        'https://boosty.to@evil.example/author/posts/id',
        'https://[boosty.to]/author/posts/id',
        'ftp://boosty.to/author/posts/id',
        'javascript:https://boosty.to/author/posts/id',
        'https://boosty.to/author/Posts/id',
        'https://boosty.to//posts/id',
        'https://boosty.to/author/posts/',
        'https://boosty.to/author/posts/id/',
        'https://boosty.to/author/posts/id/extra',
        'https://boosty.to/../posts/id',
        'https://boosty.to/author/posts/%2e%2e',
        'https://boosty.to/author%2Fother/posts/id',
        'https://boosty.to/author/posts/id%2Fother',
        'https://boosty.to/author/posts/id%5Cother',
        'https://boosty.to/author/posts/id\\other',
        'https://boosty.to/author/posts/id%00',
        'https://boosty.to/author/posts/id%FF',
        'https://boosty.to/author/posts/id%2',
        'https://boosty.to/author/posts/id?bad=%ZZ',
        'https://boosty.to/author/posts/id\n',
        '\thttps://boosty.to/author/posts/id',
        'https://boosty.to/author/posts/id with space',
        'https://boosty.to/author/posts/%20id',
        'https://boosty.to/author/posts/id%E2%80%8B',
    ],
)
def test_unrecognized_links_keep_original_target_without_lookup(href: str) -> None:
    resolver = _Resolver()
    saved = SavedPostLinks(resolver, 'author/source')

    assert parse_post_link(href) is None
    assert ViewerPostLinks(resolver)(href) == href
    assert saved(href) == href
    assert saved.unresolved == frozenset()
    assert resolver.calls == []


def test_viewer_uses_full_identity_and_preserves_suffix() -> None:
    resolver = _Resolver({_FIRST: 'author/Old title', _SECOND: 'author/Other title'})
    links = ViewerPostLinks(resolver)

    assert links(_FIRST_URL + '?mode=reader#lesson') == (
        f'/a/author/p/{_FIRST.post_id}?mode=reader#lesson'
    )
    assert links(_SECOND_URL) == f'/a/author/p/{_SECOND.post_id}'
    assert resolver.calls == [_FIRST, _SECOND]


def test_viewer_encodes_decoded_identity_once() -> None:
    identity = PostIdentity('Автор', 'opaque%2F#id')
    href = 'https://boosty.to/%D0%90%D0%B2%D1%82%D0%BE%D1%80/posts/opaque%252F%23id'
    resolver = _Resolver({identity: 'Автор/saved post'})

    assert (
        ViewerPostLinks(resolver)(href)
        == '/a/%D0%90%D0%B2%D1%82%D0%BE%D1%80/p/opaque%252F%23id'
    )


def test_saved_link_uses_stable_folder_and_encodes_special_characters_once() -> None:
    folder = 'author/Старое имя 100% #1'
    resolver = _Resolver({_FIRST: folder})
    links = SavedPostLinks(resolver, 'author/current')

    result = links(_FIRST_URL + '?original=%25#chapter')

    assert result == quote('../Старое имя 100% #1/post.html', safe='/') + (
        '?original=%25#chapter'
    )
    assert links.unresolved == frozenset()
    assert resolver.folders == {_FIRST: folder}


def test_saved_links_support_other_authors_and_self_links() -> None:
    resolver = _Resolver({_FIRST: 'author/target'})

    assert SavedPostLinks(resolver, 'other/source')(_FIRST_URL) == (
        '../../author/target/post.html'
    )
    assert SavedPostLinks(resolver, 'author/target')(_FIRST_URL) == 'post.html'


def test_unresolved_identities_are_complete_deduplicated_snapshots() -> None:
    resolver = _Resolver()
    links = SavedPostLinks(resolver, 'author/source')

    assert links(_FIRST_URL) == _FIRST_URL
    before = links.unresolved
    assert links(_FIRST_URL + '#chapter') == _FIRST_URL + '#chapter'
    assert links(_SECOND_URL) == _SECOND_URL

    assert before == frozenset({_FIRST})
    assert links.unresolved == frozenset({_FIRST, _SECOND})
    assert ViewerPostLinks(resolver)(_FIRST_URL) == _FIRST_URL


def test_unreadable_target_keeps_remote_link_and_can_be_retried() -> None:
    resolver = _Resolver(error=LibraryReadError('Invalid target snapshot'))
    saved = SavedPostLinks(resolver, 'author/source')

    assert saved(_FIRST_URL) == _FIRST_URL
    assert ViewerPostLinks(resolver)(_FIRST_URL) == _FIRST_URL
    assert saved.unresolved == frozenset({_FIRST})

    resolver.error = None
    resolver.folders[_FIRST] = 'author/now available'
    assert SavedPostLinks(resolver, 'author/source')(_FIRST_URL) == (
        '../now%20available/post.html'
    )


@pytest.mark.parametrize(
    'folder',
    [
        '',
        '/author/post',
        'other/post',
        'author',
        'author/../post',
        'author//post',
        'author\\post',
        'C:/post',
    ],
)
def test_invalid_resolver_folders_are_not_local_targets(folder: str) -> None:
    resolver = _Resolver({_FIRST: folder})
    saved = SavedPostLinks(resolver, 'author/source')

    assert saved(_FIRST_URL) == _FIRST_URL
    assert ViewerPostLinks(resolver)(_FIRST_URL) == _FIRST_URL
    assert saved.unresolved == frozenset({_FIRST})


@pytest.mark.parametrize(
    'folder',
    [
        '',
        '/author/post',
        'author',
        'author/../post',
        'author//post',
        'author\\post',
        'C:/post',
    ],
)
def test_saved_page_requires_library_relative_source_folder(folder: str) -> None:
    with pytest.raises(ValueError, match='library-relative folder'):
        SavedPostLinks(_Resolver(), folder)


def test_unexpected_resolver_errors_are_not_hidden() -> None:
    resolver = _Resolver(error=RuntimeError('Programming failure'))

    with pytest.raises(RuntimeError, match='Programming failure'):
        ViewerPostLinks(resolver)(_FIRST_URL)
    with pytest.raises(RuntimeError, match='Programming failure'):
        SavedPostLinks(resolver, 'author/source')(_FIRST_URL)
