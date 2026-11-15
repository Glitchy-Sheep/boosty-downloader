"""Saved state determines media placement, links and missing-file explanations."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import TypeAlias

import pytest

from boosty_downloader.application.page_builder import (
    InvalidStoredPostError,
    build_post_page,
)
from boosty_downloader.domain.stored_post import (
    MediaBlock,
    MediaEntry,
    MediaKind,
    MediaStatus,
    PostMetadata,
    PostSync,
    StoredPost,
)
from boosty_downloader.infrastructure.html_generator.models import (
    HtmlGenAudio,
    HtmlGenDeleted,
    HtmlGenFile,
    HtmlGenImage,
    HtmlGenMedia,
    HtmlGenNotDownloaded,
    HtmlGenRemovedMedia,
    HtmlGenUnavailable,
    HtmlGenVideo,
    UnavailableKind,
)
from boosty_downloader.infrastructure.html_generator.renderer import render_html_chunk

_NOW = datetime(2026, 10, 7, tzinfo=timezone.utc)
_POST_URL = 'https://boosty.to/author/posts/saved?part=1&next=2'
_EXTERNAL_URL = 'https://video.example:8443/watch?v=one:two&part=3'
_HtmlAttribute: TypeAlias = tuple[str, str | None]


@dataclass(frozen=True, slots=True)
class _MediaCase:
    kind: MediaKind
    media_id: str
    path: str
    missing_kind: UnavailableKind
    label: str
    expected: HtmlGenMedia


_MEDIA_CASES = [
    _MediaCase(
        MediaKind.image,
        'image:one',
        'images/saved image.jpg',
        UnavailableKind.IMAGE,
        '',
        HtmlGenImage('images/saved%20image.jpg', alt='saved image.jpg'),
    ),
    _MediaCase(
        MediaKind.file,
        'file:one',
        'files/saved archive.zip',
        UnavailableKind.FILE,
        'Author archive.zip',
        HtmlGenFile(
            'files/saved%20archive.zip', filename='Author archive.zip', size=17
        ),
    ),
    _MediaCase(
        MediaKind.audio,
        'audio:one',
        'audio/saved audio.mp3',
        UnavailableKind.AUDIO,
        'Author recording',
        HtmlGenAudio('audio/saved%20audio.mp3', title='Author recording'),
    ),
    _MediaCase(
        MediaKind.boosty_video,
        'boosty_video:one',
        'videos/saved video.mp4',
        UnavailableKind.VIDEO,
        'Author recording',
        HtmlGenVideo('videos/saved%20video.mp4', title='Author recording'),
    ),
    _MediaCase(
        MediaKind.external_video,
        f'external_video:{_EXTERNAL_URL}',
        'videos/saved external.mp4',
        UnavailableKind.VIDEO,
        'Author recording',
        HtmlGenVideo('videos/saved%20external.mp4', title='Author recording'),
    ),
]


class _RenderedMedia(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.targets: list[str] = []
        self.text: list[str] = []
        self.tags: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[_HtmlAttribute]) -> None:
        self.tags.append(tag)
        for name, value in attrs:
            if name in {'src', 'href'} and value is not None:
                self.targets.append(value)

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.text.append(data.strip())


def _entry(
    case: _MediaCase, status: MediaStatus = MediaStatus.downloaded
) -> MediaEntry:
    return MediaEntry(
        kind=case.kind,
        status=status,
        added_at=_NOW,
        position=0,
        path=case.path,
        size=17,
        filename='Author archive.zip',
        title='Author recording',
        duration=timedelta(seconds=65),
        error='Denied <request> & retry="later"',
    )


def _record(media: dict[str, MediaEntry], references: list[str]) -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            id='saved',
            author='author',
            url=_POST_URL,
            title='Saved post',
            created_at=_NOW,
            updated_at=_NOW,
        ),
        sync=PostSync(first_downloaded_at=_NOW, synced_at=_NOW),
        media=media,
        blocks=[MediaBlock(media_id) for media_id in references],
    )


@pytest.mark.parametrize('case', _MEDIA_CASES, ids=lambda case: case.kind.value)
def test_downloaded_media_uses_the_saved_path_and_author_metadata(case: _MediaCase):
    record = _record({case.media_id: _entry(case)}, [case.media_id])

    assert build_post_page(record) == [case.expected]


@pytest.mark.parametrize('case', _MEDIA_CASES, ids=lambda case: case.kind.value)
def test_pending_reserved_paths_are_cards_instead_of_local_media(case: _MediaCase):
    entry = _entry(case, MediaStatus.pending)
    record = _record({case.media_id: entry}, [case.media_id])

    chunks = build_post_page(record)

    assert len(chunks) == 1
    card = chunks[0]
    assert isinstance(card, HtmlGenNotDownloaded)
    assert card.kind is case.missing_kind
    assert card.label == case.label
    assert card.post_url == _POST_URL
    if case.kind in {MediaKind.audio, MediaKind.boosty_video, MediaKind.external_video}:
        assert card.duration == entry.duration
    html = render_html_chunk(card)
    assert case.path not in html
    assert 'src=' not in html


@pytest.mark.parametrize('case', _MEDIA_CASES, ids=lambda case: case.kind.value)
def test_user_deleted_media_is_not_rendered_from_its_retained_path(case: _MediaCase):
    record = _record(
        {case.media_id: _entry(case, MediaStatus.deleted)}, [case.media_id]
    )

    assert build_post_page(record) == [HtmlGenDeleted(case.missing_kind, case.label)]
    html = render_html_chunk(build_post_page(record)[0])
    assert 'download --restore-missing' in html
    assert case.path not in html
    assert 'src=' not in html


@pytest.mark.parametrize('case', _MEDIA_CASES, ids=lambda case: case.kind.value)
@pytest.mark.parametrize('status', [MediaStatus.failed, MediaStatus.unavailable])
def test_failed_and_unavailable_media_preserves_the_recorded_reason(
    case: _MediaCase, status: MediaStatus
):
    entry = _entry(case, status)
    card = build_post_page(_record({case.media_id: entry}, [case.media_id]))[0]

    assert isinstance(card, HtmlGenUnavailable)
    assert card.kind is case.missing_kind
    assert card.label == case.label
    assert card.reason == entry.error
    if case.kind in {MediaKind.audio, MediaKind.boosty_video, MediaKind.external_video}:
        assert card.duration == entry.duration
    if case.kind is MediaKind.external_video and status is MediaStatus.unavailable:
        assert card.source_url == _EXTERNAL_URL
    rendered = _RenderedMedia()
    rendered.feed(render_html_chunk(card))
    assert entry.error in rendered.text
    assert 'request' not in rendered.tags
    assert case.path not in rendered.targets


@pytest.mark.parametrize('case', _MEDIA_CASES, ids=lambda case: case.kind.value)
def test_saved_names_fall_back_to_the_raw_posix_basename(case: _MediaCase):
    entry = replace(
        _entry(case), title=None, filename=None, path='nested/raw %23 name.bin'
    )
    chunk = build_post_page(_record({case.media_id: entry}, [case.media_id]))[0]

    assert isinstance(chunk, (HtmlGenImage, HtmlGenVideo, HtmlGenAudio, HtmlGenFile))
    assert chunk.url == 'nested/raw%20%2523%20name.bin'
    match chunk:
        case HtmlGenImage():
            assert chunk.alt == 'raw %23 name.bin'
        case HtmlGenFile():
            assert chunk.filename == 'raw %23 name.bin'
        case HtmlGenAudio() | HtmlGenVideo():
            assert chunk.title == 'raw %23 name.bin'


@pytest.mark.parametrize('case', _MEDIA_CASES, ids=lambda case: case.kind.value)
def test_raw_paths_encode_url_syntax_once_and_render_without_changing_destination(
    case: _MediaCase,
):
    raw_path = 'media/sub dir/тест %25#?&".bin'
    expected_url = 'media/sub%20dir/%D1%82%D0%B5%D1%81%D1%82%20%2525%23%3F%26%22.bin'
    entry = replace(_entry(case), path=raw_path)
    chunk = build_post_page(_record({case.media_id: entry}, [case.media_id]))[0]

    assert isinstance(chunk, (HtmlGenImage, HtmlGenVideo, HtmlGenAudio, HtmlGenFile))
    assert chunk.url == expected_url
    rendered = _RenderedMedia()
    rendered.feed(render_html_chunk(chunk))
    assert rendered.targets
    assert set(rendered.targets) == {expected_url}


@pytest.mark.parametrize(
    ('size', 'size_text'), [(0, '0 B'), (None, None), (1536, '1.5 KB')]
)
def test_file_size_uses_actual_bytes_including_empty_and_unknown(
    size: int | None, size_text: str | None
):
    case = _MEDIA_CASES[1]
    entry = replace(_entry(case), size=size, filename='<script>A & "B"</script>.zip')
    chunk = build_post_page(_record({case.media_id: entry}, [case.media_id]))[0]

    assert isinstance(chunk, HtmlGenFile)
    assert chunk.size == size
    rendered = _RenderedMedia()
    rendered.feed(render_html_chunk(chunk))
    assert entry.filename in rendered.text
    assert 'script' not in rendered.tags
    if size_text is None:
        assert 'File · ZIP' in rendered.text
        assert not any(' B' in text or 'KB' in text for text in rendered.text)
    else:
        assert f'File · ZIP · {size_text}' in rendered.text


def test_current_order_and_repetition_follow_blocks_rather_than_inventory_position():
    image_case, file_case = _MEDIA_CASES[:2]
    inventory = {
        image_case.media_id: replace(_entry(image_case), position=0),
        file_case.media_id: replace(_entry(file_case), position=9),
    }
    record = _record(
        inventory, [file_case.media_id, image_case.media_id, file_case.media_id]
    )

    assert build_post_page(record) == [
        file_case.expected,
        image_case.expected,
        file_case.expected,
    ]


def test_removed_saved_media_is_unique_sorted_and_after_the_current_body():
    image_case, file_case, audio_case, video_case, external_case = _MEDIA_CASES
    inventory = {
        external_case.media_id: replace(
            _entry(external_case), position=8, removed_at=_NOW
        ),
        video_case.media_id: replace(_entry(video_case), position=6, removed_at=_NOW),
        audio_case.media_id: replace(_entry(audio_case), position=4, removed_at=_NOW),
        file_case.media_id: replace(_entry(file_case), position=2, removed_at=_NOW),
        image_case.media_id: replace(_entry(image_case), position=0, removed_at=_NOW),
        'image:current': replace(_entry(image_case), path='images/current.jpg'),
    }
    record = _record(inventory, ['image:current'])

    assert build_post_page(record) == [
        HtmlGenImage('images/current.jpg', alt='current.jpg'),
        HtmlGenRemovedMedia([case.expected for case in _MEDIA_CASES]),
    ]


@pytest.mark.parametrize('status', list(MediaStatus))
def test_removed_entries_need_downloaded_status_even_with_a_reserved_path(
    status: MediaStatus,
):
    case = _MEDIA_CASES[1]
    entry = replace(_entry(case, status), removed_at=_NOW)
    record = _record({case.media_id: entry}, [])

    expected = []
    if status is MediaStatus.downloaded:
        expected = [HtmlGenRemovedMedia([case.expected])]
    assert build_post_page(record) == expected


def test_inventory_entries_absent_from_body_are_not_implicitly_inserted():
    case = _MEDIA_CASES[0]

    assert build_post_page(_record({case.media_id: _entry(case)}, [])) == []


def test_missing_inventory_reference_raises_a_clear_input_error():
    record = _record({}, ['video:missing'])

    with pytest.raises(InvalidStoredPostError, match='video:missing'):
        build_post_page(record)
    assert issubclass(InvalidStoredPostError, ValueError)


@pytest.mark.parametrize('removed', [False, True], ids=['current', 'removed'])
@pytest.mark.parametrize('path', [None, ''], ids=['absent', 'empty'])
def test_downloaded_media_without_a_path_is_rejected(
    *, removed: bool, path: str | None
):
    case = _MEDIA_CASES[0]
    entry = replace(_entry(case), path=path)
    references = [case.media_id]
    if removed:
        entry.removed_at = _NOW
        references = []
    record = _record({case.media_id: entry}, references)

    with pytest.raises(InvalidStoredPostError, match=case.media_id):
        build_post_page(record)


def test_repeated_media_and_removed_sections_own_their_models_across_calls():
    case = _MEDIA_CASES[1]
    record = _record(
        {
            case.media_id: _entry(case),
            'file:removed': replace(_entry(case), removed_at=_NOW),
        },
        [case.media_id, case.media_id],
    )
    original = deepcopy(record)
    first = build_post_page(record)
    second = build_post_page(record)
    unchanged_second = deepcopy(second)
    current = first[0]
    repeated = first[1]
    section = first[2]
    assert isinstance(current, HtmlGenFile)
    assert isinstance(repeated, HtmlGenFile)
    assert isinstance(section, HtmlGenRemovedMedia)
    retained = section.media[0]
    assert isinstance(retained, HtmlGenFile)

    current.filename = 'changed current'
    retained.filename = 'changed removed'
    section.media.clear()

    assert repeated == case.expected
    assert record == original
    assert second == unchanged_second


@pytest.mark.parametrize('status', [MediaStatus.failed, MediaStatus.unavailable])
@pytest.mark.parametrize('reason', [None, ''], ids=['unknown', 'empty'])
def test_missing_error_keeps_the_fallback_explanation_in_the_renderer(
    status: MediaStatus, reason: str | None
):
    case = _MEDIA_CASES[1]
    entry = replace(_entry(case, status), error=reason)
    card = build_post_page(_record({case.media_id: entry}, [case.media_id]))[0]

    assert isinstance(card, HtmlGenUnavailable)
    assert card.reason == ''
    assert 'No reason recorded.' in render_html_chunk(card)


@pytest.mark.parametrize('case', _MEDIA_CASES[1:], ids=lambda case: case.kind.value)
def test_pending_names_use_the_reserved_basename_when_author_metadata_is_empty(
    case: _MediaCase,
):
    entry = replace(
        _entry(case, MediaStatus.pending),
        title='',
        filename='',
        path='nested/reserved %23 name.bin',
    )
    card = build_post_page(_record({case.media_id: entry}, [case.media_id]))[0]

    assert isinstance(card, HtmlGenNotDownloaded)
    assert card.label == 'reserved %23 name.bin'


@pytest.mark.parametrize(
    'status',
    [
        MediaStatus.pending,
        MediaStatus.deleted,
        MediaStatus.failed,
        MediaStatus.unavailable,
    ],
)
def test_external_video_without_a_title_or_saved_path_keeps_its_source_as_label(
    status: MediaStatus,
):
    case = _MEDIA_CASES[-1]
    entry = replace(_entry(case, status), title=None, path=None)
    card = build_post_page(_record({case.media_id: entry}, [case.media_id]))[0]

    assert isinstance(card, (HtmlGenNotDownloaded, HtmlGenDeleted, HtmlGenUnavailable))
    assert card.label == _EXTERNAL_URL


@pytest.mark.parametrize('duration', [None, timedelta(0)], ids=['unknown', 'zero'])
def test_pending_video_does_not_invent_a_duration(duration: timedelta | None):
    case = _MEDIA_CASES[-1]
    entry = replace(_entry(case, MediaStatus.pending), path=None, duration=duration)
    card = build_post_page(_record({case.media_id: entry}, [case.media_id]))[0]

    assert isinstance(card, HtmlGenNotDownloaded)
    assert card.duration == duration
