from pathlib import Path

from boosty_downloader.src.application.mappers.external_video_content import (
    PostDataChunkExternalVideo,
)
from boosty_downloader.src.domain.post import (
    PostDataChunkImage,
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.src.domain.post_data_chunks import PostDataChunkBoostyVideo
from boosty_downloader.src.infrastructure.html_generator.renderer import (
    render_post,
    render_post_to_file,
)


def test_html_generator_templates():
    chunks = [
        PostDataChunkText(
            text_fragments=[
                PostDataChunkText.TextFragment(
                    text='Welcome to my Boosty!', header_level=1
                ),
                PostDataChunkText.TextFragment(
                    text='This post includes various elements: text, media, and lists.',
                ),
                PostDataChunkText.TextFragment(text='<NEW_LINE_SYMBOL>'),
                PostDataChunkText.TextFragment(
                    text='Let’s dive in below:',
                    style=PostDataChunkText.TextFragment.TextStyle(italic=True),
                ),
            ]
        ),
        PostDataChunkText(
            text_fragments=[
                PostDataChunkText.TextFragment(text='Highlights', header_level=2),
                PostDataChunkText.TextFragment(
                    text='This paragraph contains a mix of ',
                ),
                PostDataChunkText.TextFragment(
                    text='bold',
                    style=PostDataChunkText.TextFragment.TextStyle(bold=True),
                ),
                PostDataChunkText.TextFragment(text=', '),
                PostDataChunkText.TextFragment(
                    text='italic',
                    style=PostDataChunkText.TextFragment.TextStyle(italic=True),
                ),
                PostDataChunkText.TextFragment(text=', and '),
                PostDataChunkText.TextFragment(
                    text='underlined',
                    style=PostDataChunkText.TextFragment.TextStyle(underline=True),
                ),
                PostDataChunkText.TextFragment(text=' text. You can '),
                PostDataChunkText.TextFragment(
                    text='click here',
                    link_url='https://boosty.to/example',
                    style=PostDataChunkText.TextFragment.TextStyle(underline=True),
                ),
                PostDataChunkText.TextFragment(text=' to support me.'),
            ]
        ),
        PostDataChunkTextualList(
            items=[
                PostDataChunkTextualList.ListItem(
                    data=[
                        PostDataChunkText(
                            text_fragments=[
                                PostDataChunkText.TextFragment(
                                    text='📌 What you’ll get inside:'
                                )
                            ]
                        )
                    ],
                    nested_items=[
                        PostDataChunkTextualList.ListItem(
                            data=[
                                PostDataChunkText(
                                    text_fragments=[
                                        PostDataChunkText.TextFragment(
                                            text='High-quality images'
                                        )
                                    ]
                                )
                            ],
                            nested_items=[],
                        ),
                        PostDataChunkTextualList.ListItem(
                            data=[
                                PostDataChunkText(
                                    text_fragments=[
                                        PostDataChunkText.TextFragment(
                                            text='Source files (PSD, RAW)'
                                        )
                                    ]
                                )
                            ],
                            nested_items=[],
                        ),
                        PostDataChunkTextualList.ListItem(
                            data=[
                                PostDataChunkText(
                                    text_fragments=[
                                        PostDataChunkText.TextFragment(
                                            text='Bonus video content'
                                        )
                                    ]
                                )
                            ],
                            nested_items=[
                                PostDataChunkTextualList.ListItem(
                                    data=[
                                        PostDataChunkText(
                                            text_fragments=[
                                                PostDataChunkText.TextFragment(
                                                    text='Behind the scenes'
                                                )
                                            ]
                                        )
                                    ],
                                    nested_items=[],
                                ),
                                PostDataChunkTextualList.ListItem(
                                    data=[
                                        PostDataChunkText(
                                            text_fragments=[
                                                PostDataChunkText.TextFragment(
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
        PostDataChunkImage(url='https://example.com/banner.jpg'),
        PostDataChunkBoostyVideo(
            title='Exclusive Behind the Scenes',
            url='https://example.com/video.mp4',
            quality='1080p',
        ),
        PostDataChunkExternalVideo(url='https://www.youtube.com/watch?v=dQw4w9WgXcQ'),
        PostDataChunkText(
            text_fragments=[
                PostDataChunkText.TextFragment(text='<NEW_LINE_SYMBOL>'),
                PostDataChunkText.TextFragment(
                    text='Thanks for reading!', header_level=2
                ),
                PostDataChunkText.TextFragment(
                    text='Feel free to leave a comment or suggestion below.',
                ),
            ]
        ),
    ]

    data = render_post(chunks)

    test_output_file = Path('test_output.html')

    render_post_to_file(chunks, test_output_file)

    assert test_output_file.exists()
    assert test_output_file.read_text(encoding='utf-8') == data
    assert len(data) > 0

    test_output_file.unlink(missing_ok=True)
