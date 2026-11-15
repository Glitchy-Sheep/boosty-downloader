"""Body fragments preserve saved-page grouping without document-level scripts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenFile,
    HtmlGenImage,
    HtmlGenParagraph,
    HtmlGenRemovedMedia,
    HtmlTextFragment,
)
from boosty_downloader.infrastructure.html_generator.renderer import (
    render_html,
    render_html_body,
)

if TYPE_CHECKING:
    from boosty_downloader.infrastructure.html_generator.models import HtmlGenChunk


def test_body_matches_saved_page_content_and_keeps_attachment_grouping() -> None:
    chunks: list[HtmlGenChunk] = [
        HtmlGenParagraph([HtmlTextFragment('<script>Author text</script>')]),
        HtmlGenFile('files/one.zip', 'One'),
        HtmlGenFile('files/two.zip', 'Two'),
        HtmlGenImage('images/photo.jpg'),
        HtmlGenRemovedMedia(
            [
                HtmlGenFile('files/removed.zip', 'Removed'),
                HtmlGenImage('images/old.jpg'),
            ]
        ),
    ]

    body = render_html_body(iter(chunks))
    page = render_html(chunks, 'Saved page')

    assert body in page
    assert body.count('<div class="attachments">') == 2
    assert body.index('files/one.zip') < body.index('files/two.zip')
    assert body.index('images/photo.jpg') < body.index('Removed by the author')
    assert body.index('Removed by the author') < body.index('files/removed.zip')
    assert '&lt;script&gt;Author text&lt;/script&gt;' in body
    assert all(tag not in body for tag in ['<html', '<head', '<body', '<script'])
    assert 'theme-toggle' not in body
    assert 'page-template' not in body


def test_empty_body_has_no_document_or_placeholder() -> None:
    assert render_html_body([]) == ''
