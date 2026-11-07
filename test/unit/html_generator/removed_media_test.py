from html.parser import HTMLParser
from pathlib import Path
from typing import TypeAlias

import pytest

from boosty_downloader.infrastructure.html_generator import renderer
from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenAudio,
    HtmlGenFile,
    HtmlGenImage,
    HtmlGenMedia,
    HtmlGenParagraph,
    HtmlGenRemovedMedia,
    HtmlGenVideo,
    HtmlTextFragment,
)
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html,
    render_html_chunk,
    render_html_to_file,
)

_HtmlAttribute: TypeAlias = tuple[str, str | None]


class _SectionText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.generated: list[str] = []
        self.authored: list[str] = []
        self.tags: list[str] = []
        self._generated_scope: list[bool] = []

    def handle_starttag(self, tag: str, attrs: list[_HtmlAttribute]) -> None:
        self.tags.append(tag)
        if tag not in {'img', 'source'}:
            self._generated_scope.append(
                dict(attrs).get('data-page-generated') == 'true'
            )

    def handle_endtag(self, tag: str) -> None:  # noqa: ARG002 - HTMLParser callback parameter name
        self._generated_scope.pop()

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if any(self._generated_scope):
            self.generated.append(data.strip())
        else:
            self.authored.append(data.strip())


def test_empty_removed_section_leaves_no_heading_or_page_gap() -> None:
    text = HtmlGenParagraph([HtmlTextFragment(text='Current post content')])
    empty = HtmlGenRemovedMedia(media=[])

    assert render_html_chunk(empty) == ''
    assert render_html([text, empty], page_title='Post') == render_html(
        [text], page_title='Post'
    )


@pytest.mark.parametrize(
    'media',
    [
        HtmlGenImage(url='images/saved%20image.jpg', alt='Sketch <one> & two'),
        HtmlGenVideo(url='videos/lesson.mp4', title='Lesson <one> & two'),
        HtmlGenAudio(url='audio/track.mp3', title='Track <one> & two'),
        HtmlGenFile(url='files/notes.zip', filename='Notes <one> & two.zip', size=0),
    ],
    ids=['image', 'video', 'audio', 'file'],
)
def test_removed_media_uses_its_normal_player_or_attachment(
    media: HtmlGenMedia,
) -> None:
    html = render_html_chunk(HtmlGenRemovedMedia(media=[media]))

    assert html.startswith('<section class="removed-media">')
    assert html.endswith('</section>')
    assert render_html_chunk(media).strip() in html
    assert html.count('Removed by the author') == 1
    assert html.count('Your copies stay on disk.') == 1
    assert '<one>' not in html
    assert '&amp;lt;' not in html


def test_removed_section_preserves_media_order_and_repeated_references() -> None:
    image = HtmlGenImage(url='images/repeated.jpg')
    html = render_html_chunk(
        HtmlGenRemovedMedia(
            media=[
                HtmlGenFile(url='files/first.zip', filename='First'),
                image,
                HtmlGenAudio(url='audio/middle.mp3', title='Middle'),
                image,
                HtmlGenVideo(url='videos/last.mp4', title='Last'),
            ]
        )
    )
    before_image, _, after_image = html.partition('src="images/repeated.jpg"')
    between_images, _, after_second_image = after_image.partition(
        'src="images/repeated.jpg"'
    )

    assert 'href="files/first.zip"' in before_image
    assert 'src="audio/middle.mp3"' in between_images
    assert 'src="videos/last.mp4"' in after_second_image
    assert html.count('src="images/repeated.jpg"') == 2


def test_attachment_groups_stay_inside_the_removed_section() -> None:
    html = render_html(
        [
            HtmlGenFile(url='files/before.zip', filename='Before'),
            HtmlGenRemovedMedia(
                media=[
                    HtmlGenFile(url='files/first.zip', filename='First'),
                    HtmlGenFile(url='files/second.zip', filename='Second'),
                    HtmlGenImage(url='images/between.jpg'),
                    HtmlGenFile(url='files/third.zip', filename='Third'),
                ]
            ),
            HtmlGenFile(url='files/after.zip', filename='After'),
        ],
        page_title='Retained copies',
    )
    before, _, section_and_after = html.partition('<section class="removed-media">')
    section, _, after = section_and_after.partition('</section>')
    first_group, _, rest = section.partition('</div>')

    assert before.count('<div class="attachments">') == 1
    assert after.count('<div class="attachments">') == 1
    assert section.count('<div class="attachments">') == 2
    assert 'href="files/first.zip"' in first_group
    assert 'href="files/second.zip"' in first_group
    assert rest.index('src="images/between.jpg"') < rest.index('href="files/third.zip"')
    assert 'href="files/before.zip"' not in section
    assert 'href="files/after.zip"' not in section


def test_search_markers_exclude_only_the_section_explanation() -> None:
    title = 'Lesson <script> & "notes"'
    filename = 'Sources <script> & "examples".zip'
    html = render_html_chunk(
        HtmlGenRemovedMedia(
            media=[
                HtmlGenImage(url='images/cover.jpg'),
                HtmlGenVideo(url='videos/lesson.mp4', title=title),
                HtmlGenAudio(url='audio/lesson.mp3', title='Spoken lesson'),
                HtmlGenFile(url='files/sources.zip', filename=filename),
            ]
        )
    )
    section = _SectionText()
    section.feed(html)
    section.close()

    assert section.generated == ['Removed by the author', 'Your copies stay on disk.']
    assert title in section.authored
    assert filename in section.authored
    assert 'Spoken lesson' in section.authored
    assert 'script' not in section.tags
    assert '&lt;script&gt;' in html
    assert '&amp;lt;' not in html


def test_full_page_declares_the_current_template_version_once_in_its_head(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(renderer, 'PAGE_TEMPLATE_VERSION', 23)
    html = render_html(
        [HtmlGenRemovedMedia(media=[HtmlGenImage(url='images/saved.jpg')])],
        page_title='Post <one>',
    )
    head, _, body = html.partition('</head>')

    assert '<title>Post &lt;one&gt;</title>' in head
    assert '<meta name="boosty-downloader-page-template" content="23"' in head
    assert head.count('name="boosty-downloader-page-template"') == 1
    assert 'name="boosty-downloader-page-template"' not in body


def test_saved_empty_page_also_records_its_template_version(tmp_path: Path) -> None:
    output = tmp_path / 'post' / 'index.html'

    render_html_to_file([], output, page_title='Empty post')

    html = output.read_text(encoding='utf-8')
    head = html.partition('</head>')[0]
    assert '<meta name="boosty-downloader-page-template" content="1"' in head
    assert html.count('name="boosty-downloader-page-template"') == 1
    assert '<section class="removed-media">' not in html
