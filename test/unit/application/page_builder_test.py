"""Complete pages retain text structure and media saved across download runs."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from support.synthetic_post import FIRST_TEXT, synthetic_post

from boosty_downloader.application.mappers.live_post import (
    LivePost,
    map_post_dto_to_live,
)
from boosty_downloader.application.media_paths import DiskSnapshot
from boosty_downloader.application.page_builder import build_post_page
from boosty_downloader.application.reconcile import reconcile
from boosty_downloader.domain.content_types import DownloadContentTypeFilter
from boosty_downloader.domain.post_data_chunks import (
    PostDataChunkText,
    PostDataChunkTextualList,
)
from boosty_downloader.domain.stored_post import (
    Block,
    ListBlock,
    ListItem,
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    ParagraphBreak,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.boosty_api.models.post.post import PostDTO
from boosty_downloader.infrastructure.boosty_api.models.post.post_data_types.post_data_ok_video import (
    BoostyOkVideoType,
)
from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenFile,
    HtmlGenImage,
    HtmlGenList,
    HtmlGenNotDownloaded,
    HtmlGenParagraph,
    HtmlGenRemovedMedia,
    HtmlListItem,
    HtmlListStyle,
    HtmlTextFragment,
)
from boosty_downloader.infrastructure.html_generator.renderer import render_html

FIRST = datetime(2026, 1, 1, tzinfo=timezone.utc)
LATER = FIRST + timedelta(days=7)
TextFragment = PostDataChunkText.TextFragment


def _live_post() -> LivePost:
    return map_post_dto_to_live(
        PostDTO.model_validate(synthetic_post()),
        'fixture-author',
        BoostyOkVideoType.medium,
    )


def _record(*blocks: Block) -> StoredPost:
    return StoredPost(
        post=_live_post().post,
        sync=PostSync(FIRST, FIRST),
        blocks=list(blocks),
    )


def _save_piece(record: StoredPost, kind: MediaKind, path: str) -> None:
    media_id = next(key for key, entry in record.media.items() if entry.kind is kind)
    record.media[media_id] = replace(
        record.media[media_id], status=MediaStatus.downloaded, path=path, size=40
    )


def test_empty_body_has_no_placeholder_paragraph_or_removed_section():
    assert build_post_page(_record()) == []


def test_mixed_body_flushes_text_at_lists_media_and_end_without_reordering():
    nested = ListItem([TextBlock([TextFragment('child')])])
    record = _record(
        TextBlock([TextFragment('pre')]),
        TextBlock([TextFragment('fix')]),
        ListBlock(
            [ListItem([TextBlock([TextFragment('parent')])], [nested])],
            PostDataChunkTextualList.ListStyle.ordered,
        ),
        TextBlock([TextFragment('middle')]),
        MediaBlock('image:fixture'),
        MediaBlock('image:fixture'),
        TextBlock([TextFragment('tail')]),
        ParagraphBreak(),
        ParagraphBreak(),
        TextBlock([TextFragment('end')]),
    )
    record.media['image:fixture'] = MediaEntry(
        MediaKind.image, MediaStatus.downloaded, FIRST, 0, path='images/saved.jpg'
    )
    child = HtmlListItem([HtmlGenParagraph([HtmlTextFragment('child')])])
    parent = HtmlListItem([HtmlGenParagraph([HtmlTextFragment('parent')])], [child])

    assert build_post_page(record) == [
        HtmlGenParagraph([HtmlTextFragment('pre'), HtmlTextFragment('fix')]),
        HtmlGenList([parent], HtmlListStyle.ORDERED),
        HtmlGenParagraph([HtmlTextFragment('middle')]),
        HtmlGenImage('images/saved.jpg', alt='saved.jpg'),
        HtmlGenImage('images/saved.jpg', alt='saved.jpg'),
        HtmlGenParagraph([HtmlTextFragment('tail')]),
        HtmlGenParagraph([]),
        HtmlGenParagraph([HtmlTextFragment('end')]),
    ]


def test_building_a_page_owns_text_list_data_and_styles_across_calls():
    fragment = TextFragment('shared')
    nested = ListItem([TextBlock([fragment])])
    record = _record(TextBlock([fragment]), ListBlock([ListItem([], [nested])]))
    original = deepcopy(record)
    first = build_post_page(record)
    second = build_post_page(record)
    expected = deepcopy(second)
    paragraph, listing = first
    assert isinstance(paragraph, HtmlGenParagraph)
    assert isinstance(listing, HtmlGenList)
    text = paragraph.fragments[0]
    assert isinstance(text, HtmlTextFragment)
    child = listing.items[0].nested_items[0]
    child_paragraph = child.data[0]
    assert isinstance(child_paragraph, HtmlGenParagraph)
    child_text = child_paragraph.fragments[0]
    assert isinstance(child_text, HtmlTextFragment)

    text.text = 'changed'
    text.style.bold = True
    assert child_text.text == 'shared'
    assert not child_text.style.bold
    child_text.style.italic = True
    child_paragraph.fragments.clear()
    child.data.clear()
    listing.items[0].nested_items.clear()
    listing.items.clear()
    first.clear()

    assert record == original
    assert second == expected
    assert build_post_page(record) == expected


@pytest.mark.parametrize(
    'kind', [MediaKind.file, MediaKind.boosty_video, MediaKind.audio]
)
def test_partial_runs_render_earlier_image_and_later_media_together(kind: MediaKind):
    live = _live_post()
    first = reconcile(
        None, live, DiskSnapshot({}), [DownloadContentTypeFilter.post_content], FIRST
    )
    assert first.record is not None
    _save_piece(first.record, MediaKind.image, 'images/saved.jpg')
    later = reconcile(
        first.record,
        live,
        DiskSnapshot({'images/saved.jpg': 40}),
        list(DownloadContentTypeFilter),
        LATER,
    )
    assert later.record is not None
    path = {
        MediaKind.file: 'files/archive.zip',
        MediaKind.boosty_video: 'videos/lesson.mp4',
        MediaKind.audio: 'audio/song.mp3',
    }[kind]
    _save_piece(later.record, kind, path)
    original = deepcopy(later.record)

    page = build_post_page(later.record)
    html = render_html(page, later.record.post.title)

    assert HtmlGenImage('images/saved.jpg', alt='saved.jpg') in page
    assert sum(isinstance(chunk, HtmlGenNotDownloaded) for chunk in page) == 2
    assert FIRST_TEXT in html
    assert html.count('<p><br></p>') == 2
    assert 'src="images/saved.jpg"' in html
    assert f'"{path}"' in html
    assert html.index('src="images/saved.jpg"') < html.index(f'"{path}"')
    assert html.count('Open the post on Boosty') == 2
    assert later.record == original


def test_author_removal_keeps_saved_copy_below_body_and_omits_unsaved_pieces():
    live = _live_post()
    first = reconcile(
        None, live, DiskSnapshot({}), list(DownloadContentTypeFilter), FIRST
    )
    assert first.record is not None
    _save_piece(first.record, MediaKind.image, 'images/saved.jpg')
    _save_piece(first.record, MediaKind.file, 'files/archive.zip')
    _save_piece(first.record, MediaKind.audio, 'audio/deleted.mp3')
    image_id = next(
        key for key, entry in live.media.items() if entry.kind is MediaKind.image
    )
    live.media = {image_id: live.media[image_id]}
    live.blocks = [
        block
        for block in live.blocks
        if not isinstance(block, MediaBlock) or block.media_id == image_id
    ]
    later = reconcile(
        first.record,
        live,
        DiskSnapshot({'images/saved.jpg': 40, 'files/archive.zip': 40}),
        [],
        LATER,
    )
    assert later.record is not None

    page = build_post_page(later.record)
    html = render_html(page, later.record.post.title)

    assert page[-2:] == [
        HtmlGenImage('images/saved.jpg', alt='saved.jpg'),
        HtmlGenRemovedMedia(
            [HtmlGenFile('files/archive.zip', 'fixture-archive.zip', 40)]
        ),
    ]
    assert sum(isinstance(chunk, HtmlGenRemovedMedia) for chunk in page) == 1
    assert not any(isinstance(chunk, HtmlGenNotDownloaded) for chunk in page)
    assert html.count('href="files/archive.zip"') == 1
    assert html.index('src="images/saved.jpg"') < html.index('Removed by the author')
    assert html.index('Removed by the author') < html.index('href="files/archive.zip"')
    assert 'audio/deleted.mp3' not in html
    assert 'Fixture video' not in html
