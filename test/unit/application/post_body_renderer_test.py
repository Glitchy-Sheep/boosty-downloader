"""The viewer body uses the saved-page projection with caller-owned media URLs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import quote

from boosty_downloader.application.page_builder import build_post_page
from boosty_downloader.application.post_body_renderer import StoredPostBodyRenderer
from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    LineBreak,
    ListBlock,
    ListItem,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html,
    render_html_body,
)

if TYPE_CHECKING:
    from boosty_downloader.application.ports import PostBodyRenderer

_NOW = datetime(2026, 11, 9, tzinfo=timezone.utc)
_SAVED_PATH = 'images/Фото 100% #1?.jpg'
_REMOVED_PATH = 'files/Копия 100% #2?.zip'
_PREFIX = '/media/author/post/'


def _record() -> StoredPost:
    text = TextBlock([PostDataChunkText.TextFragment('Nested <script>')])
    return StoredPost(
        post=PostMetadata(
            'post', 'author', 'https://boosty.to/author/posts/post', 'Title', _NOW, _NOW
        ),
        sync=PostSync(_NOW, _NOW),
        blocks=[
            ListBlock([ListItem([], [ListItem([text])])]),
            MediaBlock('image:saved'),
            MediaBlock('file:pending'),
        ],
        media={
            'image:saved': MediaEntry(
                MediaKind.image,
                MediaStatus.downloaded,
                _NOW,
                0,
                path=_SAVED_PATH,
                size=12,
            ),
            'file:pending': MediaEntry(MediaKind.file, MediaStatus.pending, _NOW, 1),
            'file:removed': MediaEntry(
                MediaKind.file,
                MediaStatus.downloaded,
                _NOW,
                2,
                removed_at=_NOW,
                path=_REMOVED_PATH,
                size=24,
            ),
        },
    )


def test_body_urls_are_encoded_once_and_record_is_unchanged() -> None:
    record = _record()
    before = deepcopy(record)
    calls: list[str] = []

    def media_url(path: str) -> str:
        calls.append(path)
        return _PREFIX + quote(path, safe='/')

    renderer: PostBodyRenderer = StoredPostBodyRenderer()
    body = renderer.render(record, media_url=media_url)

    assert calls == [_SAVED_PATH, _REMOVED_PATH]
    assert f'src="{_PREFIX}{quote(_SAVED_PATH, safe="/")}"' in body
    assert f'href="{_PREFIX}{quote(_REMOVED_PATH, safe="/")}"' in body
    assert 'Nested &lt;script&gt;' in body
    assert body.count('<ul>') == 2
    assert 'File not downloaded' in body
    assert 'Removed by the author' in body
    assert 'theme-toggle' not in body
    assert record == before


def test_relative_callback_matches_default_saved_page_body() -> None:
    record = _record()
    renderer = StoredPostBodyRenderer()

    body = renderer.render(record, media_url=lambda path: quote(path, safe='/'))

    assert body == render_html_body(build_post_page(record))


def _paragraph_record() -> StoredPost:
    return replace(
        _record(),
        blocks=[
            TextBlock([PostDataChunkText.TextFragment('First paragraph.')]),
            ParagraphBreak(),
            TextBlock(
                [
                    PostDataChunkText.TextFragment('Second paragraph.'),
                    LineBreak(),
                    PostDataChunkText.TextFragment('Still the second paragraph.'),
                ]
            ),
            ParagraphBreak(),
            TextBlock([PostDataChunkText.TextFragment('Third paragraph.')]),
        ],
        media={},
    )


def test_three_paragraphs_match_in_the_saved_page_and_viewer_body() -> None:
    record = _paragraph_record()
    expected = (
        '<p>First paragraph.</p>\n'
        '<p>Second paragraph.<br>Still the second paragraph.</p>\n'
        '<p>Third paragraph.</p>'
    )

    body = StoredPostBodyRenderer().render(record, media_url=lambda path: path)
    page = render_html(build_post_page(record), page_title=record.post.title)
    page_body = page.partition('<div class="content">')[2].partition('</div>')[0]

    assert body == expected
    assert page_body.strip() == expected
