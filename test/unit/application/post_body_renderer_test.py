"""The viewer body uses the saved-page projection with caller-owned media URLs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from urllib.parse import quote

import pytest

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
_PARAGRAPH_LINK = 'https://boosty.to/author/posts/paragraph'
_HEADING_LINK = 'https://boosty.to/author/posts/heading'
_LIST_LINK = 'https://boosty.to/author/posts/list'
_NESTED_LINK = 'https://boosty.to/author/posts/nested'


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


def _linked_block(text: str, url: str, *, heading: int = 0) -> TextBlock:
    return TextBlock(
        [
            PostDataChunkText.TextFragment(
                text,
                link_url=url,
                header_level=heading,
                style=PostDataChunkText.TextFragment.TextStyle(
                    bold=True, italic=True, underline=True
                ),
            )
        ]
    )


def _linked_record() -> StoredPost:
    record = _record()
    item = ListItem(
        [_linked_block('List link', _LIST_LINK)],
        [ListItem([_linked_block('Nested link', _NESTED_LINK)])],
    )
    return replace(
        record,
        blocks=[
            _linked_block('Paragraph link', _PARAGRAPH_LINK),
            ParagraphBreak(),
            _linked_block('Heading link', _HEADING_LINK, heading=2),
            ListBlock([item]),
            *record.blocks,
        ],
    )


def test_authored_links_are_separate_from_media_and_placeholder_links() -> None:
    record = _linked_record()
    before = deepcopy(record)
    link_calls: list[str] = []
    media_calls: list[str] = []
    destinations = {
        _PARAGRAPH_LINK: '/a/author/p/paragraph',
        _HEADING_LINK: '/a/author/p/heading',
        _LIST_LINK: '/a/author/p/list',
        _NESTED_LINK: '/a/author/p/nested',
    }

    def link_url(url: str) -> str:
        link_calls.append(url)
        return destinations[url]

    def media_url(path: str) -> str:
        media_calls.append(path)
        return _PREFIX + quote(path, safe='/')

    body = StoredPostBodyRenderer().render(
        record, media_url=media_url, link_url=link_url
    )

    assert link_calls == list(destinations)
    assert media_calls == [_SAVED_PATH, _REMOVED_PATH]
    assert all(f'href="{target}"' in body for target in destinations.values())
    assert '<h2><a href="/a/author/p/heading">' in body
    assert '<strong><em><u>Nested link</u></em></strong>' in body
    assert f'href="{record.post.url}" data-page-generated="true"' in body
    assert 'Open the post on Boosty' in body
    assert record == before


def test_link_callback_matches_the_saved_page_and_is_optional() -> None:
    record = _linked_record()

    def local_link(url: str) -> str:
        return '../saved/post.html#' + url.rsplit('/', 1)[-1]

    renderer = StoredPostBodyRenderer()
    body = renderer.render(record, media_url=lambda path: path, link_url=local_link)
    chunks = build_post_page(record, media_url=lambda path: path, link_url=local_link)
    page = render_html(chunks, page_title=record.post.title)

    assert body == render_html_body(chunks)
    assert body in page
    original = renderer.render(record, media_url=lambda path: path)
    assert all(
        f'href="{url}"' in original
        for url in [_PARAGRAPH_LINK, _HEADING_LINK, _LIST_LINK, _NESTED_LINK]
    )
    assert '../saved/post.html' not in original


def test_unsafe_callback_result_keeps_authored_text_without_an_anchor() -> None:
    record = replace(
        _record(), blocks=[_linked_block('Linked words', _PARAGRAPH_LINK)], media={}
    )
    body = StoredPostBodyRenderer().render(
        record,
        media_url=lambda path: path,
        link_url=lambda _url: 'javascript:alert(1)',
    )

    assert body == '<p><strong><em><u>Linked words</u></em></strong></p>'
    assert body == render_html_body(
        build_post_page(record, link_url=lambda _url: 'javascript:alert(1)')
    )


@pytest.mark.parametrize('kind', [MediaKind.boosty_video, MediaKind.external_video])
@pytest.mark.parametrize('removed', [False, True], ids=['current', 'removed'])
def test_video_and_poster_urls_are_encoded_once_in_the_shared_body(
    kind: MediaKind, *, removed: bool
) -> None:
    video_path = 'videos/Видео 100% #2?.mp4'
    preview_path = 'previews/Обложка 100% #1?.jpg'
    media_id = f'{kind.value}:saved'
    record = replace(
        _record(),
        blocks=[] if removed else [MediaBlock(media_id)],
        media={
            media_id: MediaEntry(
                kind,
                MediaStatus.downloaded,
                _NOW,
                0,
                path=video_path,
                preview_path=preview_path,
                removed_at=_NOW if removed else None,
            )
        },
    )
    before = deepcopy(record)
    calls: list[str] = []

    def media_url(path: str) -> str:
        calls.append(path)
        return _PREFIX + quote(path, safe='/')

    body = StoredPostBodyRenderer().render(record, media_url=media_url)

    assert calls == [video_path, preview_path]
    assert f'src="{_PREFIX}{quote(video_path, safe="/")}"' in body
    assert f'poster="{_PREFIX}{quote(preview_path, safe="/")}"' in body
    assert 'preload="metadata"' in body
    assert body.replace(_PREFIX, '') == render_html_body(build_post_page(record))
    assert record == before


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
