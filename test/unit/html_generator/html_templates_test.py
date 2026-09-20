import os
from pathlib import Path

import pytest

from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenAudio,
    HtmlGenChunk,
    HtmlGenFile,
    HtmlGenImage,
    HtmlGenList,
    HtmlGenText,
    HtmlGenUnavailable,
    HtmlGenVideo,
    HtmlListItem,
    HtmlListStyle,
    HtmlTextFragment,
    HtmlTextStyle,
    UnavailableKind,
)
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html,
    render_html_chunk,
    render_html_to_file,
)


def _showcase_chunks() -> list[HtmlGenChunk]:
    """Every chunk kind the page can show, with the edge cases the golden pins."""
    return [
        HtmlGenText(
            text_fragments=[
                HtmlTextFragment(text='Welcome to my Boosty!', header_level=1),
                HtmlTextFragment(
                    text='This post includes various elements: text, media, and lists.',
                ),
                HtmlTextFragment(text='\n'),
                HtmlTextFragment(
                    text="Let's dive in below:",
                    style=HtmlTextStyle(italic=True),
                ),
            ]
        ),
        HtmlGenText(
            text_fragments=[
                HtmlTextFragment(text='Highlights', header_level=2),
                HtmlTextFragment(
                    text='This paragraph contains a mix of ',
                ),
                HtmlTextFragment(
                    text='bold',
                    style=HtmlTextStyle(bold=True),
                ),
                HtmlTextFragment(text=', '),
                HtmlTextFragment(
                    text='italic',
                    style=HtmlTextStyle(italic=True),
                ),
                HtmlTextFragment(text=', and '),
                HtmlTextFragment(
                    text='underlined',
                    style=HtmlTextStyle(underline=True),
                ),
                HtmlTextFragment(text=' text. You can '),
                HtmlTextFragment(
                    text='click here',
                    link_url='https://boosty.to/example',
                    style=HtmlTextStyle(underline=True),
                ),
                HtmlTextFragment(text=' to support me.'),
            ]
        ),
        HtmlGenList(
            items=[
                HtmlListItem(
                    data=[
                        HtmlGenText(
                            text_fragments=[
                                HtmlTextFragment(text="📌 What you'll get inside:")
                            ]
                        )
                    ],
                    nested_items=[
                        HtmlListItem(
                            data=[
                                HtmlGenText(
                                    text_fragments=[
                                        HtmlTextFragment(text='High-quality images')
                                    ]
                                )
                            ],
                            nested_items=[],
                        ),
                        HtmlListItem(
                            data=[
                                HtmlGenText(
                                    text_fragments=[
                                        HtmlTextFragment(text='Source files (PSD, RAW)')
                                    ]
                                )
                            ],
                            nested_items=[],
                        ),
                        HtmlListItem(
                            data=[
                                HtmlGenText(
                                    text_fragments=[
                                        HtmlTextFragment(text='Bonus video content')
                                    ]
                                )
                            ],
                            nested_items=[
                                HtmlListItem(
                                    data=[
                                        HtmlGenText(
                                            text_fragments=[
                                                HtmlTextFragment(
                                                    text='Behind the scenes'
                                                )
                                            ]
                                        )
                                    ],
                                    nested_items=[],
                                ),
                                HtmlListItem(
                                    data=[
                                        HtmlGenText(
                                            text_fragments=[
                                                HtmlTextFragment(
                                                    text='Unreleased footage'
                                                )
                                            ]
                                        )
                                    ],
                                    nested_items=[],
                                ),
                            ],
                        ),
                    ],
                )
            ]
        ),
        HtmlGenList(
            style=HtmlListStyle.ORDERED,
            items=[
                HtmlListItem(
                    data=[
                        HtmlGenText(text_fragments=[HtmlTextFragment(text='Step one')])
                    ],
                    nested_items=[],
                ),
                HtmlListItem(
                    data=[
                        HtmlGenText(text_fragments=[HtmlTextFragment(text='Step two')])
                    ],
                    nested_items=[],
                ),
            ],
        ),
        HtmlGenImage(url='https://example.com/banner.jpg'),
        HtmlGenVideo(
            title='Exclusive Behind the Scenes',
            url='https://example.com/video.mp4',
        ),
        HtmlGenVideo(url='https://www.youtube.com/watch?v=dQw4w9WgXcQ'),
        # Pieces that did not download keep their place on the page.
        HtmlGenUnavailable(
            kind=UnavailableKind.VIDEO,
            label='https://www.youtube.com/watch?v=gone',
            reason="Couldn't download resource: External video unavailable "
            "or access restricted (can't get info)",
            source_url='https://www.youtube.com/watch?v=gone',
        ),
        HtmlGenUnavailable(
            kind=UnavailableKind.IMAGE,
            reason="Couldn't download resource: Unexpected status code: 404",
        ),
        HtmlGenText(
            text_fragments=[
                HtmlTextFragment(text='\n'),
                # A styled word inside a heading: the heading must stay one.
                HtmlTextFragment(text='Thanks for ', header_level=2),
                HtmlTextFragment(
                    text='reading', header_level=2, style=HtmlTextStyle(bold=True)
                ),
                HtmlTextFragment(text='!', header_level=2),
                HtmlTextFragment(
                    text='Feel free to leave a comment or suggestion below.',
                ),
            ]
        ),
        HtmlGenFile(
            # Markup in the name pins the escaping: it must land in HTML
            # as text, never as tags.
            url='files/release-notes.zip',
            filename='release <v2> & notes.zip',
            size=5_660_000,
        ),
        # Two files in a row share one block; this one has no size to show.
        HtmlGenFile(url='files/lesson.mp4', filename='lesson.mp4'),
        HtmlGenAudio(title='fixture-song.mp3', url='audio/fixture-song.mp3'),
    ]


def test_html_generator_templates(tmp_path: Path):
    chunks = _showcase_chunks()

    data = render_html(chunks, page_title='Showcase post')

    test_output_file = tmp_path / 'test_output.html'

    render_html_to_file(chunks, test_output_file, page_title='Showcase post')

    assert test_output_file.exists()
    assert test_output_file.read_text(encoding='utf-8') == data
    assert len(data) > 0


@pytest.mark.parametrize(
    ('filename', 'icon'),
    [
        ('clip.mp4', '🎬'),
        ('song.mp3', '🎵'),
        ('PHOTO.JPG', '🖼'),
        ('notes.txt', '📄'),
        ('slides.pdf', '📄'),
        ('archive.tar.gz', '📦'),
        ('README', '📎'),
    ],
)
def test_attachment_icon_follows_the_file_type(filename: str, icon: str) -> None:
    """A video file next to a video player must read as a file, not as a second player."""
    html = render_html_chunk(HtmlGenFile(url=f'files/{filename}', filename=filename))

    assert f'<span class="attachment-icon">{icon}</span>' in html


@pytest.mark.parametrize(
    ('filename', 'size', 'meta'),
    [
        ('стрим-1.mp4', 30383, 'File · MP4 · 29.7 KB'),
        ('notes.txt', 901, 'File · TXT · 901 B'),
        ('dataset.7z', None, 'File · 7Z'),
        ('README', 87, 'File · 87 B'),
        ('v1.2 (final)', 10, 'File · 10 B'),
    ],
    ids=['type-and-size', 'bytes', 'no-size', 'no-type', 'suffix-is-not-a-type'],
)
def test_attachment_meta_names_what_is_known(
    filename: str, size: int | None, meta: str
) -> None:
    html = render_html_chunk(HtmlGenFile(url='files/x', filename=filename, size=size))

    assert f'<span class="attachment-meta">{meta}</span>' in html


def test_neighbouring_attachments_share_one_block() -> None:
    """Nine files in a row must not become nine boxes with gaps."""
    chunks: list[HtmlGenChunk] = [
        HtmlGenFile(url='files/a.txt', filename='a.txt'),
        HtmlGenFile(url='files/b.txt', filename='b.txt'),
        HtmlGenImage(url='images/i.png'),
        HtmlGenFile(url='files/c.txt', filename='c.txt'),
    ]

    html = render_html(chunks, page_title='files')

    assert html.count('<div class="attachments">') == 2
    assert html.count('class="attachment"') == 3
    assert html.index('b.txt') < html.index('images/i.png') < html.index('c.txt')


def test_a_missing_video_names_itself_and_links_to_the_original() -> None:
    """The reader must see what is missing, why, and where to try it themselves."""
    html = render_html_chunk(
        HtmlGenUnavailable(
            kind=UnavailableKind.VIDEO,
            label='Stream <part 2>',
            reason='Unexpected status code: 403',
            source_url='https://www.youtube.com/watch?v=gone',
        )
    )

    assert 'Video not downloaded: Stream &lt;part 2&gt;' in html
    assert 'Unexpected status code: 403' in html
    assert 'href="https://www.youtube.com/watch?v=gone">Open the original</a>' in html


def test_a_missing_image_has_no_name_and_no_link() -> None:
    html = render_html_chunk(
        HtmlGenUnavailable(kind=UnavailableKind.IMAGE, reason='connection lost')
    )

    assert '<span class="unavailable-title">Image not downloaded</span>' in html
    assert 'Open the original' not in html


def test_a_styled_word_keeps_the_heading_in_one_piece() -> None:
    """One heading tag per fragment stacked three headings and dropped the style."""
    heading = HtmlGenText(
        text_fragments=[
            HtmlTextFragment(text='Hello ', header_level=2),
            HtmlTextFragment(
                text='bold', header_level=2, style=HtmlTextStyle(bold=True)
            ),
            HtmlTextFragment(text=' world', header_level=2),
        ]
    )

    assert render_html_chunk(heading) == '<h2>Hello <strong>bold</strong> world</h2>\n'


GOLDEN_FILE = Path(__file__).parents[2] / 'fixtures' / 'rendered_post.html'


def test_showcase_matches_the_pinned_golden_html():
    """A refactoring must not change a single rendered byte unnoticed.

    An intentional template change regenerates the file:
    UPDATE_GOLDEN=1 task test - then review the golden diff.
    """
    html = render_html(_showcase_chunks(), page_title='Showcase post')

    if os.environ.get('UPDATE_GOLDEN') == '1':
        GOLDEN_FILE.write_text(html, encoding='utf-8')

    assert html == GOLDEN_FILE.read_text(encoding='utf-8')
