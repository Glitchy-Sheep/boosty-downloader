from datetime import timedelta
from html.parser import HTMLParser
from typing import TypeAlias

import pytest

from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenChunk,
    HtmlGenDeleted,
    HtmlGenFile,
    HtmlGenNotDownloaded,
    HtmlGenParagraph,
    HtmlGenUnavailable,
    HtmlTextFragment,
    UnavailableKind,
)
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html,
    render_html_chunk,
)

_HtmlAttribute: TypeAlias = tuple[str, str | None]


class _CardText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.generated: list[str] = []
        self.authored: list[str] = []
        self.links: list[str] = []
        self.tags: list[str] = []
        self._generated_scope: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[_HtmlAttribute]) -> None:
        attributes = dict(attrs)
        self.tags.append(tag)
        self._generated_scope.append(attributes.get('data-page-generated') == 'true')
        if tag == 'a' and (href := attributes.get('href')) is not None:
            self.links.append(href)

    def handle_endtag(self, tag: str) -> None:  # noqa: ARG002 - HTMLParser callback parameter name

        self._generated_scope.pop()

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if any(self._generated_scope):
            self.generated.append(data.strip())
        else:
            self.authored.append(data.strip())


def _read_card(chunk: HtmlGenChunk) -> _CardText:
    card = _CardText()
    card.feed(render_html_chunk(chunk))
    card.close()
    return card


@pytest.mark.parametrize(
    ('kind', 'title'),
    [
        (UnavailableKind.IMAGE, 'Image not downloaded'),
        (UnavailableKind.VIDEO, 'Video not downloaded'),
        (UnavailableKind.AUDIO, 'Audio not downloaded'),
        (UnavailableKind.FILE, 'File not downloaded'),
    ],
)
def test_pending_card_names_its_kind_and_links_to_the_post(
    kind: UnavailableKind, title: str
) -> None:
    card = _read_card(
        HtmlGenNotDownloaded(kind=kind, post_url='https://boosty.to/author/posts/one')
    )

    assert title in card.generated
    assert card.links == ['https://boosty.to/author/posts/one']
    assert 'Open the post on Boosty' in card.generated
    assert 'video' not in card.tags
    assert 'audio' not in card.tags
    assert 'img' not in card.tags


@pytest.mark.parametrize(
    ('duration', 'display'),
    [
        (timedelta(0), '0:00'),
        (timedelta(seconds=65), '1:05'),
        (timedelta(hours=1), '1:00:00'),
        (timedelta(hours=2, minutes=3, seconds=4), '2:03:04'),
        (timedelta(hours=90, minutes=1, seconds=2), '90:01:02'),
        (timedelta(seconds=65, microseconds=900_000), '1:05'),
        (timedelta(seconds=-65), '0:00'),
    ],
    ids=['zero', 'minutes', 'hour', 'hours', 'days', 'fraction', 'negative'],
)
def test_pending_card_shows_known_duration(duration: timedelta, display: str) -> None:
    card = _read_card(
        HtmlGenNotDownloaded(
            kind=UnavailableKind.VIDEO,
            post_url='https://boosty.to/author/posts/one',
            label='Long recording',
            duration=duration,
        )
    )

    assert f'Duration: {display}' in card.generated
    assert 'Long recording' in card.authored


def test_unknown_duration_does_not_claim_a_zero_length_video() -> None:
    card = _read_card(
        HtmlGenNotDownloaded(
            kind=UnavailableKind.VIDEO,
            post_url='https://boosty.to/author/posts/one',
        )
    )

    assert not any('Duration:' in text for text in card.generated)
    assert 'None' not in card.generated


@pytest.mark.parametrize(
    ('kind', 'title'),
    [
        (UnavailableKind.IMAGE, 'Image deleted from disk'),
        (UnavailableKind.VIDEO, 'Video deleted from disk'),
        (UnavailableKind.AUDIO, 'Audio deleted from disk'),
        (UnavailableKind.FILE, 'File deleted from disk'),
    ],
)
def test_deleted_card_explains_how_to_restore_without_a_dead_local_link(
    kind: UnavailableKind, title: str
) -> None:
    card = _read_card(HtmlGenDeleted(kind=kind))

    assert title in card.generated
    assert 'download --restore-missing' in card.generated
    assert card.links == []
    assert 'video' not in card.tags
    assert 'audio' not in card.tags
    assert 'img' not in card.tags


@pytest.mark.parametrize(
    'chunk',
    [
        HtmlGenNotDownloaded(
            kind=UnavailableKind.VIDEO,
            post_url='https://boosty.to/author/posts/one',
            label='A title the reader can search',
            duration=timedelta(seconds=90),
        ),
        HtmlGenDeleted(
            kind=UnavailableKind.FILE, label='A title the reader can search'
        ),
    ],
    ids=['pending', 'deleted'],
)
def test_generated_text_markers_leave_the_author_title_searchable(
    chunk: HtmlGenChunk,
) -> None:
    card = _read_card(chunk)

    assert 'A title the reader can search' in card.authored
    assert not any('A title the reader can search' in text for text in card.generated)
    assert not any('not downloaded' in text for text in card.authored)
    assert not any('deleted from disk' in text for text in card.authored)
    assert not any('restore-missing' in text for text in card.authored)
    assert not any('Open the post' in text for text in card.authored)
    assert not any('Duration:' in text for text in card.authored)


@pytest.mark.parametrize(
    'chunk',
    [
        HtmlGenNotDownloaded(
            kind=UnavailableKind.VIDEO,
            post_url='https://boosty.to/author/posts/one?title="quoted"&part=2',
            label='<script>Title & "quotes" &lt;</script>',
        ),
        HtmlGenDeleted(
            kind=UnavailableKind.FILE,
            label='<script>Title & "quotes" &lt;</script>',
        ),
    ],
    ids=['pending', 'deleted'],
)
def test_new_cards_keep_markup_in_author_titles_as_literal_text(
    chunk: HtmlGenChunk,
) -> None:
    card = _read_card(chunk)

    assert '<script>Title & "quotes" &lt;</script>' in card.authored
    assert 'script' not in card.tags


def test_pending_post_url_is_escaped_once_without_changing_the_destination() -> None:
    post_url = 'https://boosty.to/author/posts/one?title="quoted"&part=2&literal=&amp;'
    card = _read_card(
        HtmlGenNotDownloaded(kind=UnavailableKind.FILE, post_url=post_url)
    )

    assert card.links == [post_url]


def test_unavailable_file_retains_its_name_and_recorded_error() -> None:
    html = render_html_chunk(
        HtmlGenUnavailable(
            kind=UnavailableKind.FILE,
            label='Source archive.zip',
            reason='Connection lost after 10 bytes',
        )
    )

    assert 'File not downloaded: Source archive.zip' in html
    assert 'Connection lost after 10 bytes' in html


@pytest.mark.parametrize(
    ('duration', 'display'),
    [(timedelta(0), '0:00'), (timedelta(hours=2, seconds=3), '2:00:03')],
)
def test_unavailable_video_retains_reason_title_duration_and_external_source(
    duration: timedelta, display: str
) -> None:
    card = _read_card(
        HtmlGenUnavailable(
            kind=UnavailableKind.VIDEO,
            label='Video <part 2> & "notes"',
            reason='Denied <request> & retry="later"',
            source_url='https://video.example/watch?id="one"&part=2',
            duration=duration,
        )
    )

    assert 'Video not downloaded: Video <part 2> & "notes"' in card.authored
    assert 'Denied <request> & retry="later"' in card.authored
    assert f'Duration: {display}' in card.generated
    assert card.links == ['https://video.example/watch?id="one"&part=2']
    assert 'request' not in card.tags
    assert 'part' not in card.tags


@pytest.mark.parametrize(
    ('chunk', 'title', 'reason', 'link'),
    [
        (
            HtmlGenUnavailable(kind=UnavailableKind.IMAGE, reason='Connection lost'),
            'Image not downloaded',
            'Connection lost',
            '',
        ),
        (
            HtmlGenUnavailable(
                kind=UnavailableKind.VIDEO,
                label='Stream <part 2>',
                reason='Access denied',
                source_url='https://video.example/watch?v=gone',
            ),
            'Video not downloaded: Stream &lt;part 2&gt;',
            'Access denied',
            (
                '        <a class="unavailable-link" '
                'href="https://video.example/watch?v=gone">Open the original</a>\n'
            ),
        ),
    ],
    ids=['nameless-image', 'named-video-with-source'],
)
def test_legacy_unavailable_markup_stays_unchanged_without_duration(
    chunk: HtmlGenUnavailable, title: str, reason: str, link: str
) -> None:
    assert render_html_chunk(chunk) == (
        '<div class="unavailable">\n'
        '    <span class="unavailable-icon">⚠️</span>\n'
        '    <span class="unavailable-text">\n'
        f'        <span class="unavailable-title">{title}</span>\n'
        f'        <span class="unavailable-reason">{reason}</span>\n'
        f'{link}'
        '    </span>\n'
        '</div>'
    )


def test_missing_cards_keep_their_position_between_text_and_attachment_groups() -> None:
    html = render_html(
        [
            HtmlGenParagraph([HtmlTextFragment(text='Opening paragraph')]),
            HtmlGenFile(url='files/a.zip', filename='a.zip'),
            HtmlGenNotDownloaded(
                kind=UnavailableKind.VIDEO,
                post_url='https://boosty.to/author/posts/one',
                label='Pending recording',
            ),
            HtmlGenFile(url='files/b.zip', filename='b.zip'),
            HtmlGenDeleted(kind=UnavailableKind.AUDIO, label='Deleted recording'),
            HtmlGenParagraph([HtmlTextFragment(text='Closing paragraph')]),
        ],
        page_title='Mixed saved content',
    )
    markers = [
        'Opening paragraph',
        'href="files/a.zip"',
        'Pending recording',
        'href="files/b.zip"',
        'Deleted recording',
        'Closing paragraph',
    ]
    positions = [html.index(marker) for marker in markers]

    assert positions == sorted(positions)
    assert html.count('<div class="attachments">') == 2
