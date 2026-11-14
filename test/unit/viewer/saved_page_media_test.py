"""Saved-page embedding grants apply to exact resources and real attributes only."""

from __future__ import annotations

from html import escape
from urllib.parse import quote

import pytest

from boosty_downloader.viewer.saved_page_media import (
    EMBED_TOKEN_PARAMETER,
    SavedMediaAccess,
    rewrite_saved_page,
)

_AUTHOR = 'Автор 100% #1'
_FOLDER = '2026-11-09 - Post 100% #2 (12345678)'
_PAGE = f'{_FOLDER}/post.html'


@pytest.fixture
def access() -> SavedMediaAccess:
    return SavedMediaAccess()


def _rewrite(html: str, access: SavedMediaAccess) -> str:
    return rewrite_saved_page(html, author=_AUTHOR, relative=_PAGE, access=access)


def _url(path: str, access: SavedMediaAccess) -> str:
    relative = f'{_FOLDER}/{path}'
    token = access.token_for(_AUTHOR, relative)
    encoded = quote(f'{_AUTHOR}/{relative}', safe='/')
    return f'/media/{encoded}?{EMBED_TOKEN_PARAMETER}={token}'


def test_token_is_bound_to_exact_resource_and_application(access: SavedMediaAccess):
    relative = f'{_FOLDER}/videos/Видео 100% #1?.mp4'
    token = access.token_for(_AUTHOR, relative)

    assert access.is_allowed(_AUTHOR, relative, token)
    assert token == access.token_for(_AUTHOR, relative)
    assert not access.is_allowed('other', relative, token)
    assert not access.is_allowed(_AUTHOR, relative + '.other', token)
    assert not SavedMediaAccess().is_allowed(_AUTHOR, relative, token)


@pytest.mark.parametrize('token', ['', '0', 'g' * 64, '0' * 65, 'а' * 64, '\n' * 64])
def test_malformed_tokens_are_denied(access: SavedMediaAccess, token: str):
    assert not access.is_allowed(_AUTHOR, 'post/image.png', token)


@pytest.mark.parametrize(
    ('author', 'relative'),
    [
        ('../author', 'post/image.png'),
        ('.boosty-downloader', 'post/image.png'),
        ('author\n', 'post/image.png'),
        ('author', ''),
        ('author', '/post/image.png'),
        ('author', 'post/../image.png'),
        ('author', 'post/./image.png'),
        ('author', 'post//image.png'),
        ('author', 'post\\image.png'),
        ('author', 'post/C:image.png'),
        ('author', 'post/image\x00.png'),
    ],
)
def test_noncanonical_identities_cannot_be_signed_or_verified(
    access: SavedMediaAccess, author: str, relative: str
):
    with pytest.raises(ValueError, match='canonical resource identity'):
        access.token_for(author, relative)
    assert not access.is_allowed(author, relative, '0' * 64)


@pytest.mark.parametrize(
    ('tag', 'attribute'),
    [
        ('img', 'src'),
        ('audio', 'src'),
        ('video', 'src'),
        ('source', 'src'),
        ('video', 'poster'),
    ],
)
def test_media_attributes_use_once_encoded_resource_urls(
    access: SavedMediaAccess, tag: str, attribute: str
):
    path = 'images/Фото 100% #1? & "quote".png'
    encoded = quote(path, safe='/')
    html = f'<{tag} {attribute}="{encoded}">'

    result = _rewrite(html, access)

    assert result == f'<{tag} {attribute}="{_url(path, access)}">'
    assert '%2525' not in result


def test_html_entities_decode_once_and_attribute_quotes_are_preserved(
    access: SavedMediaAccess,
):
    html = "<IMG class = 'wide' SRC = 'images/cat&amp;dog.png' alt='&copy;'>"

    result = _rewrite(html, access)

    assert result == (
        "<IMG class = 'wide' SRC = '"
        + _url('images/cat&dog.png', access)
        + "' alt='&copy;'>"
    )


def test_bare_attribute_becomes_quoted_without_reformatting_tag(
    access: SavedMediaAccess,
):
    html = '<video\n controls src=videos/movie.mp4 muted >'

    assert _rewrite(html, access) == (
        '<video\n controls src="' + _url('videos/movie.mp4', access) + '" muted >'
    )


def test_both_video_attributes_and_child_source_are_rewritten(access: SavedMediaAccess):
    html = (
        '<video src="v/main.mp4" poster="p/main.png"><source src="v/other.webm" '
        'type="video/webm"></video>'
    )
    expected = (
        f'<video src="{_url("v/main.mp4", access)}" '
        f'poster="{_url("p/main.png", access)}">'
        f'<source src="{_url("v/other.webm", access)}" type="video/webm"></video>'
    )
    assert _rewrite(html, access) == expected


@pytest.mark.parametrize(
    'url',
    [
        '',
        '/images/a.png',
        '//example.com/a.png',
        'https://example.com/a.png',
        'http://[',
        'javascript:alert(1)',
        'data:image/png;base64,AA==',
        '../other/a.png',
        './a.png',
        'images/../a.png',
        'images//a.png',
        'images/%2e%2e/a.png',
        'images/a%2fb.png',
        'images/a%5cb.png',
        'images/%00.png',
        'images/%0a.png',
        'images/a\\b.png',
        'images/a.png?x=1',
        'images/a.png#frame',
        'images/a.png?',
        'images/a.png#',
        'images/%FF.png',
        'images/%GG.png',
        'images/100%.png',
        ' images/a.png',
        '\timages/a.png',
        'images/a.png\n',
    ],
)
def test_unsupported_or_ambiguous_urls_stay_unchanged(
    access: SavedMediaAccess, url: str
):
    html = f'<img src="{escape(url, quote=True)}">'
    assert _rewrite(html, access) == html


def test_encoded_percent_is_not_decoded_as_a_second_escape(access: SavedMediaAccess):
    html = '<img src="images/%252e%252e%252f.png">'
    assert _rewrite(html, access) == (
        f'<img src="{_url("images/%2e%2e%2f.png", access)}">'
    )


@pytest.mark.parametrize(
    'html',
    [
        '<img src="a.png" src="b.png">',
        '<img SRC="a.png" src="b.png">',
        '<img src="a.png" class="one" class="two">',
        '<img/src="a.png">',
        '<img src="a.png" broken="unterminated>',
    ],
)
def test_duplicate_or_malformed_attributes_stay_unchanged(
    access: SavedMediaAccess, html: str
):
    assert _rewrite(html, access) == html


@pytest.mark.parametrize(
    'tag',
    [
        'script',
        'style',
        'textarea',
        'title',
        'xmp',
        'iframe',
        'noembed',
        'noframes',
        'noscript',
    ],
)
def test_apparent_tags_in_text_elements_stay_unchanged(
    access: SavedMediaAccess, tag: str
):
    html = f'<{tag}>literal <img src="a.png"> &amp; text</{tag}><img src="b.png">'
    expected = (
        f'<{tag}>literal <img src="a.png"> &amp; text</{tag}>'
        f'<img src="{_url("b.png", access)}">'
    )
    assert _rewrite(html, access) == expected


def test_plaintext_stays_literal_even_after_apparent_closing_tag(
    access: SavedMediaAccess,
):
    html = '<plaintext><img src="a.png"></plaintext><img src="b.png">'
    assert _rewrite(html, access) == html


def test_unrelated_source_and_links_are_preserved_exactly(access: SavedMediaAccess):
    prefix = (
        '<!DOCTYPE html>\r\n<!-- <img src="a.png"> -->\r\n'
        '<script>const text = \'<img src="a.png">\';</script>\n'
        '<a href="../other/post.html">Local &amp; link</a>\n'
        '<a href="files/a.pdf">Attachment</a>\n'
        '<div src="a.png" poster="b.png">Text &lt;img src="a.png"&gt;</div>\n'
    )
    image = '<img title=\'literal src="a.png" poster="b.png"\' src="images/c.png" />'
    expected = (
        prefix
        + '<img title=\'literal src="a.png" poster="b.png"\' src="'
        + _url('images/c.png', access)
        + '" />'
    )
    assert _rewrite(prefix + image, access) == expected


@pytest.mark.parametrize(
    'relative', ['post.html', '../post/post.html', 'post/other.html']
)
def test_unconfirmed_page_locations_stay_unchanged(
    access: SavedMediaAccess, relative: str
):
    html = '<img src="a.png">'
    assert (
        rewrite_saved_page(html, author=_AUTHOR, relative=relative, access=access)
        == html
    )
