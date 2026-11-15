import pytest

from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenHeading,
    HtmlGenList,
    HtmlGenParagraph,
    HtmlGenText,
    HtmlInline,
    HtmlLineBreak,
    HtmlListItem,
    HtmlListStyle,
    HtmlTextFragment,
    HtmlTextStyle,
)
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html,
    render_html_chunk,
)


def test_adjacent_fragments_keep_their_spacing_and_styles() -> None:
    paragraph = HtmlGenParagraph(
        fragments=[
            HtmlTextFragment(text='down'),
            HtmlTextFragment(text='load', style=HtmlTextStyle(bold=True)),
            HtmlTextFragment(text='ed'),
        ]
    )

    assert render_html_chunk(paragraph) == '<p>down<strong>load</strong>ed</p>'


def test_text_and_link_attributes_are_escaped_once() -> None:
    paragraph = HtmlGenParagraph(
        fragments=[
            HtmlTextFragment(
                text='<NEW_LINE_SYMBOL> & <script> "quoted"',
                link_url='https://example.test/?title="quoted"&part=2',
                style=HtmlTextStyle(bold=True, italic=True, underline=True),
            )
        ]
    )

    assert render_html_chunk(paragraph) == (
        '<p><a href="https://example.test/?title=&#34;quoted&#34;&amp;part=2">'
        '<strong><em><u>&lt;NEW_LINE_SYMBOL&gt; &amp; &lt;script&gt; '
        '&#34;quoted&#34;</u></em></strong></a></p>'
    )


@pytest.mark.parametrize('level', range(1, 7))
def test_heading_level_belongs_to_the_block(level: int) -> None:
    heading = HtmlGenHeading(
        level=level,
        fragments=[
            HtmlTextFragment(text='First ', header_level=3),
            HtmlTextFragment(
                text='part', header_level=5, style=HtmlTextStyle(bold=True)
            ),
            HtmlLineBreak(),
            HtmlTextFragment(text='Second part'),
        ],
    )

    assert render_html_chunk(heading) == (
        f'<h{level}>First <strong>part</strong><br>Second part</h{level}>'
    )


def test_paragraph_ignores_legacy_fragment_heading_fields() -> None:
    paragraph = HtmlGenParagraph(
        fragments=[HtmlTextFragment(text='Body', header_level=2)]
    )

    assert render_html_chunk(paragraph) == '<p>Body</p>'


def test_typed_breaks_stay_inside_one_paragraph() -> None:
    paragraph = HtmlGenParagraph(
        fragments=[
            HtmlLineBreak(),
            HtmlTextFragment(text='First'),
            HtmlLineBreak(),
            HtmlLineBreak(),
            HtmlTextFragment(text='Second'),
            HtmlLineBreak(),
        ]
    )

    assert render_html_chunk(paragraph) == '<p><br>First<br><br>Second<br></p>'


@pytest.mark.parametrize('text', ['\n', '\r\n', 'left\nright'])
def test_raw_newline_text_is_not_a_typed_break(text: str) -> None:
    paragraph = HtmlGenParagraph(fragments=[HtmlTextFragment(text=text)])

    assert render_html_chunk(paragraph) == f'<p>{text}</p>'


@pytest.mark.parametrize(
    'fragments',
    [[], [HtmlTextFragment(text='')]],
    ids=['no-fragments', 'empty-text'],
)
def test_empty_paragraph_keeps_a_visible_blank_line(
    fragments: list[HtmlInline],
) -> None:
    assert render_html_chunk(HtmlGenParagraph(fragments=fragments)) == '<p><br></p>'


def test_complete_page_keeps_consecutive_empty_paragraphs() -> None:
    html = render_html(
        [
            HtmlGenParagraph(fragments=[]),
            HtmlGenParagraph(fragments=[]),
            HtmlGenParagraph(fragments=[HtmlTextFragment(text='Body')]),
            HtmlGenParagraph(fragments=[]),
        ],
        page_title='Blank lines',
    )

    assert '<p><br></p>\n<p><br></p>\n<p>Body</p>\n<p><br></p>' in html


@pytest.mark.parametrize(
    ('style', 'tag'),
    [(HtmlListStyle.ORDERED, 'ol'), (HtmlListStyle.UNORDERED, 'ul')],
)
def test_nested_lists_render_mixed_legacy_and_structured_text(
    style: HtmlListStyle, tag: str
) -> None:
    listing = HtmlGenList(
        style=style,
        items=[
            HtmlListItem(
                data=[
                    HtmlGenText(text_fragments=[HtmlTextFragment(text='Legacy')]),
                    HtmlGenParagraph(fragments=[HtmlTextFragment(text='Parent')]),
                ],
                nested_items=[
                    HtmlListItem(
                        data=[
                            HtmlGenHeading(
                                level=3,
                                fragments=[HtmlTextFragment(text='Child')],
                            )
                        ],
                        nested_items=[HtmlListItem(data=[HtmlGenParagraph([])])],
                    )
                ],
            )
        ],
    )

    html = render_html_chunk(listing)

    assert html.count(f'<{tag}>') == 3
    assert html.count(f'</{tag}>') == 3
    assert html.count('<li>') == 3
    assert '<p>Parent</p>' in html
    assert '<h3>Child</h3>' in html
    assert '<p><br></p>' in html
    assert html.index('Legacy') < html.index('Parent') < html.index('Child')


def test_legacy_text_keeps_its_newline_interpretation() -> None:
    legacy = HtmlGenText(text_fragments=[HtmlTextFragment(text='\n')])

    assert render_html_chunk(legacy) == '<br>\n'
