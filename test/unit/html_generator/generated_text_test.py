from dataclasses import dataclass
from datetime import timedelta
from html.parser import HTMLParser
from typing import Final, TypeAlias

import pytest

from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenChunk,
    HtmlGenFile,
    HtmlGenUnavailable,
    UnavailableKind,
)
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html,
    render_html_body,
)

_HtmlAttribute: TypeAlias = tuple[str, str | None]
_VOID_TAGS: Final = frozenset(
    {
        'area',
        'base',
        'br',
        'col',
        'embed',
        'hr',
        'img',
        'input',
        'link',
        'meta',
        'param',
        'source',
        'track',
        'wbr',
    }
)


@dataclass(frozen=True, slots=True)
class _TextScope:
    in_card: bool = False
    generated: bool = False


class _CardText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.authored: list[str] = []
        self.generated: list[str] = []
        self._scopes = [_TextScope()]

    def handle_starttag(self, tag: str, attrs: list[_HtmlAttribute]) -> None:
        if tag in _VOID_TAGS:
            return
        attributes = dict(attrs)
        parent = self._scopes[-1]
        self._scopes.append(
            _TextScope(
                in_card=parent.in_card
                or attributes.get('class') in {'attachment', 'unavailable'},
                generated=parent.generated
                or attributes.get('data-page-generated') == 'true'
                or attributes.get('aria-hidden') == 'true',
            )
        )

    def handle_endtag(self, tag: str) -> None:
        if tag not in _VOID_TAGS:
            self._scopes.pop()

    def handle_data(self, data: str) -> None:
        scope = self._scopes[-1]
        if not scope.in_card or not data.strip():
            return
        target = self.generated if scope.generated else self.authored
        target.append(data.strip())


def _card_text(chunks: list[HtmlGenChunk], *, full_page: bool) -> _CardText:
    html = render_html(chunks, 'Saved post') if full_page else render_html_body(chunks)
    parser = _CardText()
    parser.feed(html)
    parser.close()
    return parser


@pytest.mark.parametrize('full_page', [False, True], ids=['body', 'saved-page'])
@pytest.mark.parametrize(
    'source_url', ['https://example.com/video', 'javascript:bad()']
)
def test_unavailable_card_searches_only_the_author_label(
    *, full_page: bool, source_url: str
) -> None:
    card = _card_text(
        [
            HtmlGenUnavailable(
                kind=UnavailableKind.VIDEO,
                label='Video <lesson>',
                reason='Connection lost',
                source_url=source_url,
                duration=timedelta(seconds=65),
            )
        ],
        full_page=full_page,
    )

    assert card.authored == ['Video <lesson>']
    assert card.generated == [
        '⚠️',
        'Video not downloaded:',
        'Connection lost',
        'Duration: 1:05',
        'Open the original',
    ]


@pytest.mark.parametrize('full_page', [False, True], ids=['body', 'saved-page'])
def test_nameless_unavailable_card_has_no_searchable_labels(*, full_page: bool) -> None:
    card = _card_text(
        [HtmlGenUnavailable(kind=UnavailableKind.IMAGE, reason='')],
        full_page=full_page,
    )

    assert card.authored == []
    assert card.generated == ['⚠️', 'Image not downloaded', 'No reason recorded.']


@pytest.mark.parametrize('full_page', [False, True], ids=['body', 'saved-page'])
def test_attachment_name_remains_searchable_without_its_type_or_size(
    *, full_page: bool
) -> None:
    card = _card_text(
        [
            HtmlGenFile(
                url='files/source.zip', filename='Authored archive.zip', size=1024
            )
        ],
        full_page=full_page,
    )

    assert 'Authored archive.zip' in card.authored
    assert card.generated == ['File · ZIP · 1.0 KB']
    assert not any('File ·' in text for text in card.authored)
