from pathlib import Path

from boosty_downloader.src.infrastructure.html_generator.models import (
    HtmlGenChunk,
    HtmlGenImage,
    HtmlGenList,
    HtmlGenText,
    HtmlGenVideo,
    HtmlListItem,
    HtmlTextFragment,
    HtmlTextStyle,
)
from boosty_downloader.src.infrastructure.html_generator.renderer import (
    render_html,
    render_html_to_file,
)


def test_html_generator_templates():
    chunks: list[HtmlGenChunk] = [
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
    ]

    data = render_html(chunks)

    test_output_file = Path('test_output.html')

    render_html_to_file(chunks, test_output_file)

    assert test_output_file.exists()
    assert test_output_file.read_text(encoding='utf-8') == data
    assert len(data) > 0

    test_output_file.unlink(missing_ok=True)
