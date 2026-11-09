"""Author links keep their text without granting executable URL schemes."""

from collections.abc import Callable
from html.parser import HTMLParser
from typing import TypeAlias

import pytest

from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenChunk,
    HtmlGenHeading,
    HtmlGenList,
    HtmlGenNotDownloaded,
    HtmlGenParagraph,
    HtmlGenText,
    HtmlGenUnavailable,
    HtmlListItem,
    HtmlTextFragment,
    HtmlTextStyle,
    UnavailableKind,
)
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html,
    render_html_body,
)

_HtmlAttribute: TypeAlias = tuple[str, str | None]
_LinkContainer: TypeAlias = Callable[[str], HtmlGenChunk]
_LABEL = 'Visible <script> & "quoted" text'


class _RenderedLinks(HTMLParser):
    def __init__(self, html: str) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.text: list[str] = []
        self.tags: list[str] = []
        self.feed(html)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[_HtmlAttribute]) -> None:
        self.tags.append(tag)
        href = dict(attrs).get('href')
        if tag == 'a' and href is not None:
            self.links.append(href)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def _text(url: str) -> HtmlGenChunk:
    return HtmlGenText([HtmlTextFragment(_LABEL, link_url=url)])


def _paragraph(url: str) -> HtmlGenChunk:
    fragment = HtmlTextFragment(_LABEL, link_url=url, style=HtmlTextStyle(bold=True))
    return HtmlGenParagraph([fragment])


def _heading(url: str) -> HtmlGenChunk:
    return HtmlGenHeading(2, [HtmlTextFragment(_LABEL, link_url=url)])


def _nested_list(url: str) -> HtmlGenChunk:
    text = HtmlGenParagraph([HtmlTextFragment(_LABEL, link_url=url)])
    return HtmlGenList([HtmlListItem([], [HtmlListItem([text])])])


def _unavailable(url: str) -> HtmlGenChunk:
    return HtmlGenUnavailable(UnavailableKind.VIDEO, '', label=_LABEL, source_url=url)


def _pending(url: str) -> HtmlGenChunk:
    return HtmlGenNotDownloaded(UnavailableKind.VIDEO, post_url=url, label=_LABEL)


@pytest.mark.parametrize(
    'container', [_text, _paragraph, _heading, _nested_list, _unavailable, _pending]
)
@pytest.mark.parametrize(
    'url',
    [
        'javascript:alert(1)',
        'JaVaScRiPt:alert(1)',
        '\x00\x1f javascript:alert(1) \x00',
        'java\tscript:alert(1)',
        '\njava\rscript\n:alert(1)',
        'data:text/html,<script>alert(1)</script>',
        'vbscript:msgbox(1)',
        'file:///private/path',
        'ftp://example.test/file',
        'blob:https://example.test/object',
        'custom+app.action:run',
    ],
)
def test_unsafe_links_keep_visible_text_in_every_author_link_container(
    container: _LinkContainer, url: str
) -> None:
    chunk = container(url)
    body = render_html_body([chunk])
    rendered = _RenderedLinks(body)

    assert rendered.links == []
    assert 'a' not in rendered.tags
    assert 'script' not in rendered.tags
    assert _LABEL in ''.join(rendered.text)
    assert body in render_html([chunk], 'Page')


@pytest.mark.parametrize(
    'container', [_text, _paragraph, _heading, _nested_list, _unavailable, _pending]
)
@pytest.mark.parametrize(
    'url',
    [
        'http://example.test/path',
        'HTTPS://example.test/?value="quoted"&next=2',
        'mailto:author@example.test',
        '/a/author/p/post',
        '../other/post.html',
        './files/notes%20%25.txt',
        '#section',
        '?search=текст',
        '//example.test/path',
        '/javascript:relative-path',
        'javascript%3Arelative-path',
    ],
)
def test_allowed_links_survive_exactly_once_after_html_escaping(
    container: _LinkContainer, url: str
) -> None:
    rendered = _RenderedLinks(render_html_body([container(url)]))

    assert rendered.links == [url]
    assert _LABEL in ''.join(rendered.text)
    assert 'script' not in rendered.tags


@pytest.mark.parametrize(
    ('chunk', 'label'),
    [
        (_unavailable('javascript:run()'), 'Open the original'),
        (_pending('javascript:run()'), 'Open the post on Boosty'),
    ],
)
def test_disallowed_card_link_keeps_its_label_as_plain_text(
    chunk: HtmlGenChunk, label: str
) -> None:
    rendered = _RenderedLinks(render_html_body([chunk]))

    assert label in ''.join(rendered.text)
    assert rendered.links == []
