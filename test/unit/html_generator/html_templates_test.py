import os
from pathlib import Path

from boosty_downloader.src.infrastructure.html_generator.models import (
    HtmlGenAudio,
    HtmlGenChunk,
    HtmlGenFile,
    HtmlGenImage,
    HtmlGenList,
    HtmlGenText,
    HtmlGenVideo,
    HtmlListItem,
    HtmlListStyle,
    HtmlTextFragment,
    HtmlTextStyle,
)
from boosty_downloader.src.infrastructure.html_generator.renderer import (
    render_html,
    render_html_to_file,
)


def _showcase_chunks() -> list[HtmlGenChunk]:
    """Fresh chunks per call: the renderer mutates video and audio urls in place."""
    return [
        HtmlGenText(
            text_fragments=[
                HtmlTextFragment(text='Welcome to my Boosty!', header_level=1),
                HtmlTextFragment(
                    text='This post includes various elements: text, media, and lists.',
                ),
                HtmlTextFragment(text='<NEW_LINE_SYMBOL>'),
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
        HtmlGenText(
            text_fragments=[
                HtmlTextFragment(text='<NEW_LINE_SYMBOL>'),
                HtmlTextFragment(text='Thanks for reading!', header_level=2),
                HtmlTextFragment(
                    text='Feel free to leave a comment or suggestion below.',
                ),
            ]
        ),
        HtmlGenFile(
            # The markup in the name pins current renderer behavior: file links
            # are built with a plain f-string, the name goes into HTML unescaped.
            url='files/release-notes.zip',
            filename='release <v2> & notes.zip',
        ),
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
